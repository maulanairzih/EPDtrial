import os
import requests
import base64
import time # BARU: Diperlukan untuk timestamp SpeechSuper
import hashlib # BARU: Diperlukan untuk signature (sig) SpeechSuper
import json # BARU: Diperlukan untuk membuat JSON payload SpeechSuper
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# --- Fungsi untuk Language Confidence dan SpeechAce (Tidak Berubah) ---

def proses_language_confidence(audio_file, prompt_text):
    """Memproses asesmen dengan memanggil API Language Confidence."""
    # ... (kode ini tetap sama)
    lc_api_key = os.getenv("LC_API_KEY")
    if not lc_api_key:
        return {'error': 'Konfigurasi server LC tidak lengkap.'}
    endpoint = "https://apis.languageconfidence.ai/speech-assessment/unscripted/us"
    audio_content = audio_file.read()
    audio_base64 = base64.b64encode(audio_content).decode('utf-8')
    audio_format = audio_file.filename.split('.')[-1]
    payload = { "audio_base64": audio_base64, "audio_format": audio_format, "context": { "question": prompt_text } }
    headers = { 'Content-Type': 'application/json', 'api-key': lc_api_key }
    print(f"Mengirim request ke Language Confidence...")
    try:
        response = requests.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        api_data = response.json()
        score = api_data.get('overall', {}).get('overall_score', 'N/A')
        feedback = api_data.get('metadata', {}).get('content_relevance_feedback', 'Tidak ada feedback.')
        transcript = api_data.get('metadata', {}).get('predicted_text', '')
        return { 'api_sumber': 'Language Confidence (Live)', 'score': round(score, 2) if isinstance(score, (int, float)) else score, 'feedback': feedback, 'transcript': transcript }
    except requests.exceptions.RequestException as e:
        print(f"Error menghubungi Language Confidence: {e}")
        return {'error': f'Gagal terhubung ke layanan LC. Error: {e}'}, 500

def proses_speechace(audio_file, prompt_text):
    """Memproses asesmen dengan memanggil API SpeechAce."""
    # ... (kode ini tetap sama)
    sa_api_key = os.getenv("SA_API_KEY")
    if not sa_api_key:
        return {'error': 'Konfigurasi server SA tidak lengkap.'}
    endpoint = "https://api2.speechace.com/api/scoring/speech/v0.5/json"
    params = { 'key': sa_api_key, 'dialect': 'en-us', 'user_id': 'LND-APP-001' }
    files = { 'user_audio_file': (audio_file.filename, audio_file.read(), audio_file.content_type) }
    data = { 'relevance_context': prompt_text, 'include_ielts_subscore': 1 }
    print(f"Mengirim request ke SpeechAce di endpoint baru...")
    try:
        response = requests.post(endpoint, params=params, data=data, files=files)
        response.raise_for_status()
        api_data = response.json()
        score = api_data.get('ielts_estimate', 'N/A')
        transcript = api_data.get('transcript', 'Tidak ada transkrip.')
        relevance = api_data.get('relevance.class', True)
        feedback = f"Jawaban Anda dinilai relevan: {relevance}."
        return { 'api_sumber': 'SpeechAce (Live)', 'score': score, 'feedback': feedback, 'transcript': transcript }
    except requests.exceptions.RequestException as e:
        print(f"Error menghubungi SpeechAce: {e}")
        return {'error': f'Gagal terhubung ke layanan SA. Error: {e}'}, 500


# --- FUNGSI SPEECHSUPER YANG DIPERBARUI ---

def proses_speechsuper(audio_file, prompt_text):
    """Memproses asesmen dengan memanggil API SpeechSuper."""
    app_key = os.getenv("SS_APP_KEY")
    secret_key = os.getenv("SS_SECRET_KEY")

    if not all([app_key, secret_key]):
        return {'error': 'Konfigurasi server SS (appKey/secretKey) tidak lengkap.'}

    # 1. Tentukan coreType dan siapkan endpoint
    core_type = "asr.eval" # Sesuai dokumentasi untuk Unscripted General Speech Assessment
    endpoint = f"https://api.speechsuper.com/{core_type}"

    # 2. Buat timestamp dan signature (sig)
    timestamp = str(int(time.time()))
    user_id = "guest-user" # ID pengguna anonim
    
    # Signature untuk 'connect'
    connect_sig_text = app_key + timestamp + secret_key
    connect_sig = hashlib.sha1(connect_sig_text.encode('utf-8')).hexdigest()

    # Signature untuk 'start'
    start_sig_text = app_key + timestamp + user_id + secret_key
    start_sig = hashlib.sha1(start_sig_text.encode('utf-8')).hexdigest()

    # 3. Buat payload JSON yang kompleks sesuai dokumentasi
    assessment_params = {
        "connect": {
            "cmd": "connect",
            "param": { "sdk": { "version": 16777472, "source": 9, "protocol": 2 },
                       "app": { "applicationId": app_key, "timestamp": timestamp, "sig": connect_sig } }
        },
        "start": {
            "cmd": "start",
            "param": {
                "app": { "userId": user_id, "applicationId": app_key, "timestamp": timestamp, "sig": start_sig },
                "audio": { "audioType": audio_file.filename.split('.')[-1], "channel": 1, "sampleBytes": 2, "sampleRate": 16000 },
                "request": { "coreType": core_type, "tokenId": "some_unique_token_id" }
            }
        }
    }

    # 4. Siapkan request multipart/form-data
    # 'text' berisi JSON, dan 'audio' berisi file audio
    files = {
        'text': (None, json.dumps(assessment_params), 'application/json'),
        'audio': (audio_file.filename, audio_file.read(), 'application/octet-stream')
    }
    
    print(f"Mengirim request ke SpeechSuper...")
    try:
        response = requests.post(endpoint, files=files)
        response.raise_for_status()
        api_data = response.json()

        # 5. Ekstrak data relevan dari respons
        # Berdasarkan contoh respons, skor ada di 'result.overall'
        result = api_data.get('result', {})
        score = result.get('overall', 'N/A')
        transcript = result.get('recognition', 'Tidak ada transkrip.')
        feedback = f"Pronunciation Score: {result.get('pronunciation', 'N/A')}, Fluency: {result.get('fluency', 'N/A')}."

        return { 'api_sumber': 'SpeechSuper (Live)', 'score': score, 'feedback': feedback, 'transcript': transcript }
    except requests.exceptions.RequestException as e:
        print(f"Error menghubungi SpeechSuper: {e}")
        # Cetak respons error dari server jika ada, untuk debugging
        if e.response:
            print(f"Server Response: {e.response.text}")
        return {'error': f'Gagal terhubung ke layanan SS. Error: {e}'}, 500

# === Rute (Routes) Flask (Tidak ada perubahan) ===
@app.route('/')
def index():
    """Menyajikan halaman utama aplikasi (index.html)."""
    return render_template('index.html')

@app.route('/analisis_master', methods=['POST'])
def analisis_master():
    """Menerima data audio dan prompt, lalu mengarahkannya ke fungsi pemroses yang sesuai."""
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
    return jsonify(hasil)

if __name__ == '__main__':
    app.run(debug=True, port=5000)