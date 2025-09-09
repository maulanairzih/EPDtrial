import os
import requests
import base64
import time
import hashlib
import json
import random
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Konfigurasi dasar
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
# Konfigurasi untuk SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app) # Inisialisasi database

# Membuat model untuk tabel hasil evaluasi
class HasilEvaluasi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), nullable=False)
    api_sumber = db.Column(db.String(100), nullable=False)
    score = db.Column(db.String(10), nullable=True)
    feedback = db.Column(db.Text, nullable=True)
    transcript = db.Column(db.Text, nullable=True)
    tanggal_tes = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<Hasil {self.user_id} - {self.api_sumber}>'

# === Fungsi Pemroses API ===

def proses_language_confidence(audio_file, prompt_text):
    """Memproses asesmen dengan memanggil API Language Confidence."""
    lc_api_key = os.getenv("LC_API_KEY")
    if not lc_api_key:
        return {'error': 'Konfigurasi server LC tidak lengkap.'}

    endpoint = "https://apis.languageconfidence.ai/speech-assessment/unscripted/us"
    
    audio_content = audio_file.read()
    audio_base64 = base64.b64encode(audio_content).decode('utf-8')
    audio_format = audio_file.filename.split('.')[-1]

    payload = {
      "audio_base64": audio_base64,
      "audio_format": audio_format,
      "context": {
        "question": prompt_text
      }
    }
    
    headers = {
      'Content-Type': 'application/json',
      'api-key': lc_api_key
    }

    print(f"Mengirim request ke Language Confidence...")
    try:
        response = requests.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        api_data = response.json()
        
        score = api_data.get('overall', {}).get('overall_score', 'N/A')
        feedback = api_data.get('metadata', {}).get('content_relevance_feedback', 'Tidak ada feedback.')
        transcript = api_data.get('metadata', {}).get('predicted_text', '')

        return {
            'api_sumber': 'Language Confidence (Live)',
            'score': round(score, 2) if isinstance(score, (int, float)) else score,
            'feedback': feedback,
            'transcript': transcript
        }
    except requests.exceptions.RequestException as e:
        print(f"Error menghubungi Language Confidence: {e}")
        if e.response:
            print(f"LC Error Response: {e.response.text}")
        return {'error': f'Gagal terhubung ke layanan LC. Error: {e}'}, 500


def proses_speechace(audio_file, prompt_text):
    """Memproses asesmen dengan memanggil API SpeechAce."""
    sa_api_key = os.getenv("SA_API_KEY")
    if not sa_api_key:
        return {'error': 'Konfigurasi server SA tidak lengkap.'}

    endpoint = "https://api2.speechace.com/api/scoring/speech/v0.5/json"
    
    params = {
        'key': sa_api_key,
        'dialect': 'en-us',
        'user_id': 'LND-APP-001'
    }

    files = {
        'user_audio_file': (audio_file.filename, audio_file.read(), audio_file.content_type)
    }
    
    data = {
        'relevance_context': prompt_text,
        'include_ielts_subscore': 1
    }
    
    print(f"Mengirim request ke SpeechAce di endpoint baru...")
    try:
        response = requests.post(endpoint, params=params, data=data, files=files)
        response.raise_for_status()
        api_data = response.json()
        
        score = api_data.get('ielts_estimate', 'N/A')
        transcript = api_data.get('transcript', 'Tidak ada transkrip.')
        relevance = api_data.get('relevance.class', True)

        feedback = f"Jawaban Anda dinilai relevan: {relevance}."
        
        return {
            'api_sumber': 'SpeechAce (Live)',
            'score': score,
            'feedback': feedback,
            'transcript': transcript
        }
    except requests.exceptions.RequestException as e:
        print(f"Error menghubungi SpeechAce: {e}")
        if e.response:
            print(f"SA Error Response: {e.response.text}")
        return {'error': f'Gagal terhubung ke layanan SA. Error: {e}'}, 500


def proses_speechsuper(audio_file, prompt_text):
    """Memproses asesmen dengan memanggil API SpeechSuper."""
    app_key = os.getenv("SS_APP_KEY")
    secret_key = os.getenv("SS_SECRET_KEY")

    if not all([app_key, secret_key]):
        return {'error': 'Konfigurasi server SS (appKey/secretKey) tidak lengkap.'}

    core_type = "asr.eval"
    endpoint = f"https://api.speechsuper.com/{core_type}"
    timestamp = str(int(time.time()))
    user_id = "guest-user"
    
    token_id = f"token-{timestamp}-{random.randint(1000, 9999)}"

    connect_sig_text = app_key + timestamp + secret_key
    connect_sig = hashlib.sha1(connect_sig_text.encode('utf-8')).hexdigest()
    start_sig_text = app_key + timestamp + user_id + secret_key
    start_sig = hashlib.sha1(start_sig_text.encode('utf-8')).hexdigest()

    assessment_params = {
        "connect": { "cmd": "connect", "param": { "sdk": { "version": 16777472, "source": 9, "protocol": 2 }, "app": { "applicationId": app_key, "timestamp": timestamp, "sig": connect_sig } } },
        "start": { "cmd": "start", "param": { "app": { "userId": user_id, "applicationId": app_key, "timestamp": timestamp, "sig": start_sig }, "audio": { "audioType": audio_file.filename.split('.')[-1], "channel": 1, "sampleBytes": 2, "sampleRate": 16000 }, "request": { "coreType": core_type, "tokenId": token_id } } }
    }

    files = { 'text': (None, json.dumps(assessment_params), 'application/json'), 'audio': (audio_file.filename, audio_file.read(), 'application/octet-stream') }
    
    print(f"Mengirim request ke SpeechSuper...")
    try:
        response = requests.post(endpoint, files=files)
        response.raise_for_status()
        api_data = response.json()
        result = api_data.get('result', {})
        score = result.get('overall', 'N/A')
        transcript = result.get('recognition', 'Tidak ada transkrip.')
        feedback = f"Pronunciation Score: {result.get('pronunciation', 'N/A')}, Fluency: {result.get('fluency', 'N/A')}."
        return { 'api_sumber': 'SpeechSuper (Live)', 'score': score, 'feedback': feedback, 'transcript': transcript }
    except requests.exceptions.RequestException as e:
        print(f"Error menghubungi SpeechSuper: {e}")
        if e.response:
            print(f"SS Error Response: {e.response.text}")
        return {'error': f'Gagal terhubung ke layanan SS. Error: {e}'}, 500

# === Rute (Routes) Flask ===
@app.route('/')
def index():
    """Menyajikan halaman utama aplikasi (index.html)."""
    return render_template('index.html')


@app.route('/analisis_master', methods=['POST'])
def analisis_master():
    """Menerima data audio, memproses, dan menyimpan hasilnya ke database."""
    if 'audio' not in request.files or 'apiChoice' not in request.form:
        return jsonify({'error': 'Request tidak lengkap'}), 400
        
    audio_file = request.files['audio']
    api_choice = request.form.get('apiChoice')
    prompt_text = request.form.get('promptText')

    hasil = {}
    if api_choice == 'lc':
        hasil = proses_language_confidence(audio_file, prompt_text)
    elif api_choice == 'sa':
        hasil = proses_speechace(audio_file, prompt_text)
    elif api_choice == 'ss':
        hasil = proses_speechsuper(audio_file, prompt_text)
    else:
        return jsonify({'error': 'Pilihan API tidak valid'}), 400

    if 'error' not in hasil:
        evaluasi_baru = HasilEvaluasi(
            user_id="karyawan-001",
            api_sumber=hasil.get('api_sumber'),
            score=str(hasil.get('score')),
            feedback=hasil.get('feedback'),
            transcript=hasil.get('transcript')
        )
        db.session.add(evaluasi_baru)
        db.session.commit()
        print("Hasil evaluasi berhasil disimpan ke database.")

    return jsonify(hasil)

if __name__ == '__main__':
    app.run(debug=True, port=5000)