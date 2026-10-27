"""Publie le prochain Reel de queue.json sur Instagram (API Instagram Login)."""
import json, os, sys, time, subprocess, zipfile, shutil, datetime
import requests

DRY = os.environ.get("DRY_RUN", "false").lower() == "true"
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
REPO = os.environ["GITHUB_REPOSITORY"]
DROPBOX = os.environ["DROPBOX_FOLDER_URL"]  # lien partagé du dossier, avec dl=1
API = "https://graph.instagram.com/v23.0"

queue = json.load(open("queue.json", encoding="utf-8"))
state = json.load(open("state.json"))

# prochain élément non ignoré
i = state["next"]
while i < len(queue) and queue[i]["skip"]:
    i += 1
if i >= len(queue):
    print("File d'attente terminée.")
    sys.exit(0)
item = queue[i]
print(f"Prochaine vidéo : #{item['n']} {item['file']}")

# 1) renouveler le token (60 jours) à chaque exécution
if TOKEN:
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": TOKEN}, timeout=60)
    print("refresh token:", r.status_code)

# 2) télécharger le dossier Dropbox (zip) et extraire la vidéo du jour
os.makedirs("work", exist_ok=True)
zpath = "work/folder.zip"
with requests.get(DROPBOX, stream=True, timeout=600, allow_redirects=True) as r:
    r.raise_for_status()
    with open(zpath, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
out = f"work/reel_{item['n']:02d}.mp4"
with zipfile.ZipFile(zpath) as z:
    match = [m for m in z.namelist() if m.split("/")[-1] == item["file"]]
    if not match:
        sys.exit(f"Fichier introuvable dans le zip : {item['file']}")
    with z.open(match[0]) as src, open(out, "wb") as dst:
        shutil.copyfileobj(src, dst)
os.remove(zpath)
print("vidéo extraite :", os.path.getsize(out), "octets")

# 3) héberger temporairement la vidéo sur la branche orpheline "media"
def sh(*a):
    subprocess.run(a, check=True)
sh("git", "config", "user.name", "reels-bot")
sh("git", "config", "user.email", "reels-bot@users.noreply.github.com")
sh("git", "checkout", "--orphan", "media")
sh("git", "rm", "-rf", "--cached", ".")
sh("git", "add", "-f", out)
sh("git", "commit", "-m", f"media {item['n']}")
sh("git", "push", "-f", "origin", "media")
video_url = f"https://raw.githubusercontent.com/{REPO}/media/{out}"
print("URL vidéo :", video_url)
sh("git", "checkout", "-f", "main")

if DRY:
    print("DRY_RUN : arrêt avant l'appel Instagram.")
    sys.exit(0)

# 4) créer le conteneur Reel, attendre le traitement, publier
r = requests.post(f"{API}/me/media", data={
    "media_type": "REELS", "video_url": video_url,
    "caption": item["caption"], "share_to_feed": "true",
    "access_token": TOKEN}, timeout=120)
print(r.status_code, r.text)
r.raise_for_status()
cid = r.json()["id"]
for _ in range(60):
    s = requests.get(f"{API}/{cid}", params={"fields": "status_code,status", "access_token": TOKEN}, timeout=60).json()
    print(s)
    if s.get("status_code") == "FINISHED":
        break
    if s.get("status_code") in ("ERROR", "EXPIRED"):
        sys.exit(f"Échec du traitement : {s}")
    time.sleep(20)
else:
    sys.exit("Délai dépassé pendant le traitement vidéo")
r = requests.post(f"{API}/me/media_publish", data={"creation_id": cid, "access_token": TOKEN}, timeout=120)
print(r.status_code, r.text)
r.raise_for_status()

state["next"] = i + 1
state["published"].append({"n": item["n"], "id": r.json().get("id"),
                           "at": datetime.datetime.utcnow().isoformat() + "Z"})
json.dump(state, open("state.json", "w"), indent=1)
print("Publié.")
