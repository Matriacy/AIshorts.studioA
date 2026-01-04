import os, time, uuid, sqlite3, shutil, requests
from flask import Flask, request, jsonify, send_from_directory, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from openai import OpenAI
from elevenlabs import ElevenLabs

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
load_dotenv()

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
eleven = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

DB = "auth.db"

VOICE_MAP = {
    "en-us": "21m00Tcm4TlvDq8ikWAM",  # Rachel
    "en-uk": "AZnzlk1XvdvUeBnXmlld",
    "es": "TxGEqnHWrfWFTfGW9XjX",
    "fr": "pNInz6obpgDQGcFmaJgB",
    "de": "ErXwobaYiN019PkySvjV"
}

AVATARS = {
    "female_pro": "https://create-images-results.d-id.com/DefaultPresenters/amy/image.jpeg",
    "male_pro": "https://create-images-results.d-id.com/DefaultPresenters/daniel/image.jpeg",
    "creator": "https://create-images-results.d-id.com/DefaultPresenters/jess/image.jpeg",
    "motivational": "https://create-images-results.d-id.com/DefaultPresenters/jack/image.jpeg"
}

# -------------------------------------------------
# DATABASE
# -------------------------------------------------
def db():
    return sqlite3.connect(DB)

def init_db():
    con = db()
    con.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        password TEXT,
        credits INTEGER DEFAULT 5
    )
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        prompt TEXT,
        video_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    con.commit()
    con.close()

init_db()

def current_user():
    if "uid" not in session:
        return None
    con = db()
    u = con.execute(
        "SELECT id,email,credits FROM users WHERE id=?",
        (session["uid"],)
    ).fetchone()
    con.close()
    return u

# -------------------------------------------------
# PAGE ROUTES (HTML)
# -------------------------------------------------
@app.route("/")
def home():
    return redirect("/login")

@app.route("/login")
def login_page():
    return send_from_directory("static", "login.html")

@app.route("/register")
def register_page():
    return send_from_directory("static", "register.html")

@app.route("/dashboard")
def dashboard_page():
    if not current_user():
        return redirect("/login")
    return send_from_directory("static", "dashboard.html")

@app.route("/create")
def create_page():
    if not current_user():
        return redirect("/login")
    return send_from_directory("static", "create.html")

@app.route("/admin")
def admin_page():
    return send_from_directory("static", "admin.html")

# -------------------------------------------------
# AUTH API
# -------------------------------------------------
@app.route("/api/register", methods=["POST"])
def register():
    d = request.json
    try:
        con = db()
        con.execute(
            "INSERT INTO users(email,password) VALUES (?,?)",
            (d["email"], generate_password_hash(d["password"]))
        )
        con.commit()
        con.close()
        return jsonify(success=True)
    except:
        return jsonify(error="Email exists"), 400

@app.route("/api/login", methods=["POST"])
def login():
    d = request.json
    con = db()
    u = con.execute(
        "SELECT id,password FROM users WHERE email=?",
        (d["email"],)
    ).fetchone()
    con.close()
    if not u or not check_password_hash(u[1], d["password"]):
        return jsonify(error="Invalid login"), 401
    session["uid"] = u[0]
    return jsonify(success=True)

@app.route("/api/logout")
def logout():
    session.clear()
    return redirect("/login")

# -------------------------------------------------
# AI HELPERS
# -------------------------------------------------
def generate_script(prompt):
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150
    )
    return r.choices[0].message.content.strip()

def generate_voice(text, lang):
    audio_stream = eleven.text_to_speech.convert(
        voice_id=VOICE_MAP.get(lang, VOICE_MAP["en-us"]),
        text=text,
        model_id="eleven_multilingual_v2"
    )
    path = "static/voice.mp3"
    with open(path, "wb") as f:
        for chunk in audio_stream:
            f.write(chunk)
    return "/static/voice.mp3"

def generate_avatar(avatar_key, voice_url):
    headers = {
        "Authorization": f"Basic {os.getenv('DID_API_KEY')}",
        "Content-Type": "application/json"
    }
    payload = {
        "source_url": AVATARS[avatar_key],
        "script": {
            "type": "audio",
            "audio_url": voice_url
        }
    }
    r = requests.post("https://api.d-id.com/talks", headers=headers, json=payload).json()
    tid = r["id"]
    for _ in range(30):
        s = requests.get(
            f"https://api.d-id.com/talks/{tid}",
            headers=headers
        ).json()
        if s.get("status") == "done":
            return s["result_url"]
        time.sleep(1)
    raise Exception("Avatar generation timeout")

# -------------------------------------------------
# GENERATE VIDEO
# -------------------------------------------------
@app.route("/api/generate", methods=["POST"])
def generate():
    u = current_user()
    if not u:
        return jsonify(error="Unauthorized"), 401
    if u[2] <= 0:
        return jsonify(error="No credits"), 402

    d = request.json
    script = generate_script(d["prompt"])
    voice = generate_voice(script, d["language"])
    video_url = generate_avatar(d["avatar"], voice)

    local = f"static/{uuid.uuid4()}.mp4"
    with open(local, "wb") as f:
        shutil.copyfileobj(requests.get(video_url, stream=True).raw, f)

    con = db()
    con.execute("UPDATE users SET credits=credits-1 WHERE id=?", (u[0],))
    con.execute(
        "INSERT INTO history(user_id,prompt,video_url) VALUES (?,?,?)",
        (u[0], d["prompt"], local)
    )
    con.commit()
    con.close()

    return jsonify(video="/" + local, credits=u[2] - 1)

# -------------------------------------------------
# DASHBOARD DATA
# -------------------------------------------------
@app.route("/api/dashboard")
def dashboard_data():
    u = current_user()
    if not u:
        return jsonify(error="Unauthorized"), 401
    con = db()
    h = con.execute(
        "SELECT prompt, video_url FROM history WHERE user_id=? ORDER BY id DESC",
        (u[0],)
    ).fetchall()
    con.close()
    return jsonify(
        email=u[1],
        credits=u[2],
        history=[{"prompt":x[0], "video":x[1]} for x in h]
    )

# -------------------------------------------------
# HEALTH CHECK
# -------------------------------------------------
@app.route("/health")
def health():
    return jsonify(ok=True)

# -------------------------------------------------
# RUN
# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
