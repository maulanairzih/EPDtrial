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

# Membuat tabel database jika belum ada
with app.app_context():
    db.create_all()
    print("Database tables created successfully!")

# === Fungsi Pemroses API ===

def proses_language_confidence(audio_file, prompt_text):
    """Memproses asesmen dengan memanggil API Language Confidence."""
    lc_api_key = os.getenv("LC_API_KEY")
    if not lc_api_key:
        return {'error': 'Konfigurasi server LC tidak lengkap.'}

    endpoint = "https://apis.languageconfidence.ai/speech-assessment/unscripted/us"
    
    # Reset file pointer ke awal
    audio_file.seek(0)
    audio_content = audio_file.read()
    audio_base64 = base64.b64encode(audio_content).decode('utf-8')
    audio_format = audio_file.filename.split('.')[-1].lower()
    
    # Pastikan format audio yang didukung
    if audio_format not in ['wav', 'mp3', 'webm', 'm4a', 'ogg']:
        audio_format = 'webm'  # Default untuk browser recording

    payload = {
        "audio_base64": audio_base64,
        "audio_format": audio_format,
        "context": {
            "question": prompt_text if prompt_text else "Tell me about yourself"
        }
    }
    
    headers = {
        'Content-Type': 'application/json',
        'api-key': lc_api_key
    }

    print(f"Mengirim request ke Language Confidence...")
    print(f"Audio format: {audio_format}, Size: {len(audio_content)} bytes")
    
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        api_data = response.json()
        
        # Parsing response dengan error handling
        overall_data = api_data.get('overall', {})
        metadata = api_data.get('metadata', {})
        
        score = overall_data.get('overall_score', 'N/A')
        feedback = metadata.get('content_relevance_feedback', 'Tidak ada feedback.')
        transcript = metadata.get('predicted_text', 'Tidak ada transkrip.')

        return {
            'api_sumber': 'Language Confidence (Live)',
            'score': round(score, 2) if isinstance(score, (int, float)) else str(score),
            'feedback': feedback,
            'transcript': transcript
        }
    except requests.exceptions.RequestException as e:
        print(f"Error menghubungi Language Confidence: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"LC Error Response: {e.response.text}")
            error_msg = f'Language Confidence Error: {e.response.status_code}'
        else:
            error_msg = f'Connection Error: {str(e)}'
        return {'error': error_msg}


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

    # Reset file pointer ke awal
    audio_file.seek(0)
    
    files = {
        'user_audio_file': (audio_file.filename, audio_file.read(), audio_file.content_type)
    }
    
    data = {
        'relevance_context': prompt_text if prompt_text else "Tell me about yourself",
        'include_ielts_subscore': 1,
        'include_fluency': 1,
        'include_pronunciation': 1
    }
    
    print(f"Mengirim request ke SpeechAce...")
    try:
        response = requests.post(endpoint, params=params, data=data, files=files, timeout=30)
        response.raise_for_status()
        api_data = response.json()
        
        # Parsing response dengan error handling
        score = api_data.get('ielts_estimate', 'N/A')
        transcript = api_data.get('transcript', 'Tidak ada transkrip.')
        
        # Check relevance - handle nested structure
        relevance_data = api_data.get('relevance', {})
        if isinstance(relevance_data, dict):
            relevance = relevance_data.get('class', True)
        else:
            relevance = True

        # Build comprehensive feedback
        fluency = api_data.get('fluency', {})
        pronunciation = api_data.get('pronunciation', {})
        
        feedback_parts = [f"Jawaban dinilai relevan: {relevance}."]
        
        if isinstance(fluency, dict) and 'score' in fluency:
            feedback_parts.append(f"Fluency: {fluency['score']}")
        
        if isinstance(pronunciation, dict) and 'score' in pronunciation:
            feedback_parts.append(f"Pronunciation: {pronunciation['score']}")
            
        feedback = " ".join(feedback_parts)
        
        return {
            'api_sumber': 'SpeechAce (Live)',
            'score': str(score),
            'feedback': feedback,
            'transcript': transcript
        }
    except requests.exceptions.RequestException as e:
        print(f"Error menghubungi SpeechAce: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"SA Error Response: {e.response.text}")
            error_msg = f'SpeechAce Error: {e.response.status_code}'
        else:
            error_msg = f'Connection Error: {str(e)}'
        return {'error': error_msg}


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
    
    # Generate unique token ID
    token_id = f"token-{timestamp}-{random.randint(1000, 9999)}"

    # Generate signatures
    connect_sig_text = app_key + timestamp + secret_key
    connect_sig = hashlib.sha1(connect_sig_text.encode('utf-8')).hexdigest()
    start_sig_text = app_key + timestamp + user_id + secret_key
    start_sig = hashlib.sha1(start_sig_text.encode('utf-8')).hexdigest()

    # Reset file pointer ke awal
    audio_file.seek(0)
    audio_content = audio_file.read()
    
    # Determine audio format
    audio_format = audio_file.filename.split('.')[-1].lower()
    if audio_format not in ['wav', 'mp3', 'webm', 'ogg']:
        audio_format = 'webm'

    assessment_params = {
        "connect": {
            "cmd": "connect",
            "param": {
                "sdk": {
                    "version": 16777472,
                    "source": 9,
                    "protocol": 2
                },
                "app": {
                    "applicationId": app_key,
                    "timestamp": timestamp,
                    "sig": connect_sig
                }
            }
        },
        "start": {
            "cmd": "start",
            "param": {
                "app": {
                    "userId": user_id,
                    "applicationId": app_key,
                    "timestamp": timestamp,
                    "sig": start_sig
                },
                "audio": {
                    "audioType": audio_format,
                    "channel": 1,
                    "sampleBytes": 2,
                    "sampleRate": 16000
                },
                "request": {
                    "coreType": core_type,
                    "tokenId": token_id,
                    "refText": prompt_text if prompt_text else ""
                }
            }
        }
    }

    files = {
        'text': (None, json.dumps(assessment_params), 'application/json'),
        'audio': (audio_file.filename, audio_content, 'application/octet-stream')
    }
    
    print(f"Mengirim request ke SpeechSuper...")
    print(f"Token ID: {token_id}")
    
    try:
        response = requests.post(endpoint, files=files, timeout=30)
        response.raise_for_status()
        api_data = response.json()
        
        # Check for API-level errors
        if api_data.get('error'):
            error_code = api_data.get('error', {}).get('code', 'Unknown')
            error_msg = api_data.get('error', {}).get('message', 'Unknown error')
            print(f"SpeechSuper API Error: {error_code} - {error_msg}")
            return {'error': f'SpeechSuper API Error: {error_msg}'}
        
        result = api_data.get('result', {})
        score = result.get('overall', 'N/A')
        transcript = result.get('recognition', 'Tidak ada transkrip.')
        
        # Build feedback
        pronunciation = result.get('pronunciation', 'N/A')
        fluency = result.get('fluency', 'N/A')
        feedback = f"Pronunciation Score: {pronunciation}, Fluency: {fluency}."
        
        return {
            'api_sumber': 'SpeechSuper (Live)',
            'score': str(score),
            'feedback': feedback,
            'transcript': transcript
        }
    except requests.exceptions.RequestException as e:
        print(f"Error menghubungi SpeechSuper: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"SS Error Response: {e.response.text}")
            error_msg = f'SpeechSuper Error: {e.response.status_code}'
        else:
            error_msg = f'Connection Error: {str(e)}'
        return {'error': error_msg}

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
    prompt_text = request.form.get('promptText', '')

    # Validate audio file
    if audio_file.filename == '':
        return jsonify({'error': 'File audio tidak ditemukan'}), 400

    # Process based on API choice
    hasil = None
    if api_choice == 'lc':
        hasil = proses_language_confidence(audio_file, prompt_text)
    elif api_choice == 'sa':
        hasil = proses_speechace(audio_file, prompt_text)
    elif api_choice == 'ss':
        hasil = proses_speechsuper(audio_file, prompt_text)
    else:
        return jsonify({'error': 'Pilihan API tidak valid'}), 400

    # Check if hasil is valid dictionary (not tuple)
    if not isinstance(hasil, dict):
        return jsonify({'error': 'Unexpected response format from API processor'}), 500

    # Handle errors from API
    if 'error' in hasil:
        return jsonify(hasil), 500

    # Save to database
    try:
        evaluasi_baru = HasilEvaluasi(
            user_id="karyawan-001",
            api_sumber=hasil.get('api_sumber', 'Unknown'),
            score=str(hasil.get('score', 'N/A')),
            feedback=hasil.get('feedback', 'Tidak ada feedback.'),
            transcript=hasil.get('transcript', 'Tidak ada transkrip.')
        )
        db.session.add(evaluasi_baru)
        db.session.commit()
        print("Hasil evaluasi berhasil disimpan ke database.")
    except Exception as e:
        print(f"Error saving to database: {e}")
        db.session.rollback()
        # Still return the result even if database save fails
        hasil['warning'] = 'Data berhasil diproses tapi gagal disimpan ke database.'

    return jsonify(hasil)


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint untuk monitoring."""
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()}), 200


if __name__ == '__main__':
    app.run(debug=True, port=5000)