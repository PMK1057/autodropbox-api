print("Le script démarre...")
import os
from google.oauth2.service_account import Credentials
from google.cloud import texttospeech
import cloudinary
import cloudinary.uploader
import cloudinary.api
import requests
import multiprocessing
import random
from flask import Flask, jsonify, request
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json
from flask_cors import CORS


data_in_memory = []

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 🌍 Variables d'environnement
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY', '')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '')
STABILITY_API_KEY = os.environ.get('STABILITY_API_KEY', '')
STABILITY_ENDPOINT = os.environ.get(
    'STABILITY_ENDPOINT',
    'https://api.stability.ai/v2beta/stable-image/generate/ultra'
)
STABILITY_REFERENCE_IMAGE_PATH = os.environ.get('STABILITY_REFERENCE_IMAGE_PATH')
FIREBASE_CREDENTIALS_JSON = os.environ.get('FIREBASE_CREDENTIALS_JSON')
FIREBASE_CREDENTIALS_PATH = os.environ.get('FIREBASE_CREDENTIALS_PATH')


# 🔐 Charge la clé privée Firebase
google_creds_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON') or FIREBASE_CREDENTIALS_JSON
if google_creds_json:
    cred_info = json.loads(google_creds_json)
    cred = credentials.Certificate(cred_info)
    SERVICE_ACCOUNT_FILE = os.path.join(SCRIPT_DIR, 'service_account.json')
    with open(SERVICE_ACCOUNT_FILE, 'w') as tmp_file:
        json.dump(cred_info, tmp_file)
elif FIREBASE_CREDENTIALS_PATH and os.path.exists(FIREBASE_CREDENTIALS_PATH):
    SERVICE_ACCOUNT_FILE = FIREBASE_CREDENTIALS_PATH
    cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
else:
    SERVICE_ACCOUNT_FILE = os.path.join(SCRIPT_DIR, 'serviceaccountkey.json')
    cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)

# ✅ Initialise Firebase si pas déjà fait
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", SERVICE_ACCOUNT_FILE)

# 🔗 Connexion Firestore
db = firestore.client()

google_creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
tts_client = texttospeech.TextToSpeechClient(credentials=google_creds)
print("Connexion à Google Cloud Text-to-Speech réussie")

data_lock = multiprocessing.Lock()   # 🔒 protège l’accès à `data`

# Initialisation de Flask
app = Flask(__name__)
CORS(app)

@app.route('/start-script', methods=['GET'])
def start_script():
    try:
        result = run_main_script() or {}
        return jsonify({"status": "ok", **result}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



@app.route('/upload-json', methods=['POST'])
def upload_json():
    global data_in_memory
    try:
        content = request.get_data(as_text=True)
        print("📥 Requête reçue sur /upload-json")
        print(f"🔎 Données brutes reçues (200 premiers caractères) : {content[:200]}")
        
        data_in_memory = json.loads(content)
        print(f"✅ JSON chargé. Nombre d'éléments : {len(data_in_memory)}")
        
        return jsonify({"status": "ok", "message": "Fichier reçu"}), 200
    except Exception as e:
        print(f"❌ Erreur pendant le chargement JSON : {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        
        
@app.route('/generate-questions', methods=['POST'])
def generate_questions():
    try:
        print("=" * 50)
        print("🔥 DÉBUT generate_questions")
        
        data = request.get_json()
        print(f"📥 Data reçue : {data}")
        
        phrases = data.get('phrases', '')
        category = data.get('category', '')
        niveau = data.get('niveau', 1)
        langue_user = data.get('langue_user', 'Español')
        langue_to_learn = data.get('langue_to_learn', 'Français')
        suggestions_instructions = data.get('suggestions_instructions', '')
        
        print(f"📝 Génération pour : {phrases[:50]}...")
        print(f"📋 Catégorie: {category}, Niveau: {niveau}")
        print(f"🌍 {langue_user} → {langue_to_learn}")
        if suggestions_instructions:
            print(f"⚙️ Instructions suggestions : {suggestions_instructions}")
        
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY manquant")
        
        print(f"🔑 Clé API (10 premiers char): {ANTHROPIC_API_KEY[:10]}...")
        
        # Adaptation automatique de l'accent selon la langue à apprendre
        accent_map = {
            'Français': 'fr-FR',
            'Español': 'es-ES',
            'English': 'en-US',
            'Anglais': 'en-GB'
        }
        accent_tts = accent_map.get(langue_to_learn, 'fr-FR')
        print(f"🎙️ Accent TTS sélectionné : {accent_tts}")
        
        # Templates de questions selon la langue du user
        langue_to_learn_display = {
            'Français': {'Español': 'francés', 'English': 'French'},
            'Español': {'English': 'Spanish', 'Français': 'espagnol'},
            'English': {'Español': 'inglés', 'Français': 'anglais'}
        }
        
        # Récupère le nom de la langue dans la langue du user
        langue_display = langue_to_learn_display.get(langue_to_learn, {}).get(langue_user, langue_to_learn.lower())
        print(f"🌍 Langue affichée : {langue_display}")
        
        # Instruction personnalisée pour les suggested_answers
        if suggestions_instructions:
            suggestions_guide = f"""

INSTRUCTIONS SPÉCIALES pour les "suggested_answers" :
{suggestions_instructions}

Applique ces instructions lors de la génération des 3 mauvaises réponses.
"""
        else:
            suggestions_guide = "Par défaut : inclure des synonymes, des mots proches, ou des expressions similaires."
        
        prompt = f"""Tu reçois une liste de mots ou de phrases en {langue_to_learn} que des élèves dont la langue principale est {langue_user} doivent apprendre.

Pour CHAQUE entrée fournie, génère un objet JSON avec :

- "mot" : la traduction du mot ou de la phrase {langue_to_learn} vers {langue_user}
- "correct_answer" : le mot ou la phrase originale en {langue_to_learn}
- "q2_content" : une question en {langue_user} qui demande comment dire cette traduction dans la langue {langue_to_learn}. Formule la question naturellement pour un apprenant {langue_user}.
- "suggested_answers" : 4 propositions en {langue_to_learn}, séparées par " | ".
  La PREMIÈRE option doit être exactement {{"correct_answer"}} (le mot/phrase original).
  Les 3 autres doivent être des erreurs plausibles (fautes de grammaire, faux-amis, mots proches mais incorrects, etc.) et ne doivent PAS être des synonymes exacts.
  {suggestions_guide}
- "texte_explicatif" : une explication en {langue_user} qui aide l’apprenant à comprendre la bonne réponse (contexte, nuance, règle…).

Liste à traiter :
{phrases}

Format JSON :
[
  {{
    "category_q2": "{category}",
    "q2_content": "[question en {langue_user}]",
    "question_level": {niveau},
    "correct_answer": "[mot/phrase en {langue_to_learn}]",
    "suggested_answers": "[bonne réponse en {langue_to_learn}] | [mauvaise réponse 1] | [mauvaise réponse 2] | [mauvaise réponse 3]",
    "words_count": 2,
    "langue_to_learn": "{langue_to_learn}",
    "langue_user": "{langue_user}",
    "mot": "[traduction en {langue_user}]",
    "texte_explicatif": "[explication en {langue_user}]",
    "sound_link": "",
    "dl_link": "",
    "accent_tts": "{accent_tts}",
    "index_tts": "3",
    "image_yesno": "no",
    "image_link": "",
    "image_prompt": "",
    "type": "gen"
  }}
]

RAPPEL CRUCIAL :
- Entrée reçue = mots/phrases en {langue_to_learn}
- "mot" = traduction en {langue_user}
- "correct_answer" = mot/phrase original en {langue_to_learn}
- "suggested_answers" = toutes en {langue_to_learn} (bonne réponse + 3 erreurs plausibles)
- L’audio sera généré pour "correct_answer" avec la voix {accent_tts}

IMPORTANT - FORMAT JSON :
- Assure-toi que TOUTES les apostrophes et guillemets dans les strings sont valides
- N'utilise PAS de retours à la ligne dans les strings JSON
- Le JSON doit être strictement valide et parsable
- Si un texte contient des apostrophes ('), garde-les telles quelles (le JSON les gère)
"""
        
        print("📤 Appel à l'API Anthropic...")
        
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 8000,
                'messages': [{'role': 'user', 'content': prompt}]
            }
        )
        
        print(f"📊 Status code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ Erreur API Anthropic : {response.status_code}")
            print(f"📄 Réponse : {response.text}")
            return jsonify({"status": "error", "message": f"Erreur API: {response.status_code}"}), 500
        
        print("✅ Réponse reçue de l'API")
        
        claude_response = response.json()
        print(f"📦 Claude response keys: {claude_response.keys()}")
        
        json_text = claude_response['content'][0]['text'].strip()
        print(f"📝 JSON brut (100 premiers char): {json_text[:100]}...")
        
        # Nettoie les backticks et markdown
        json_text = json_text.replace('```json', '').replace('```', '').strip()
        
        # Trouve le début et la fin du tableau JSON
        start_idx = json_text.find('[')
        end_idx = json_text.rfind(']')
        
        if start_idx != -1 and end_idx != -1:
            json_text = json_text[start_idx:end_idx+1]
        
        print("🧹 JSON nettoyé, parsing...")
        print(f"📏 Taille du JSON : {len(json_text)} caractères")
        
        # Sauvegarde le JSON pour debug si besoin
        if len(json_text) > 50000:
            print("⚠️ JSON très long, possible problème")
        
        questions = json.loads(json_text.strip())
        
        print(f"✅ {len(questions)} questions générées")
        print("=" * 50)
        
        return jsonify({"status": "ok", "questions": questions}), 200
        
    except json.JSONDecodeError as e:
        print("=" * 50)
        print(f"❌ ERREUR JSON : {e}")
        print(f"📄 JSON problématique (1000 premiers char):")
        print(json_text[:1000])
        print("...")
        print(f"📄 JSON problématique (1000 derniers char):")
        print(json_text[-1000:])
        print("=" * 50)
        return jsonify({"status": "error", "message": f"JSON invalide: {str(e)}"}), 500
    except Exception as e:
        print("=" * 50)
        print(f"❌❌❌ ERREUR CRITIQUE : {e}")
        import traceback
        traceback.print_exc()
        print("=" * 50)
        return jsonify({"status": "error", "message": str(e)}), 500
        
        
        
@app.route('/generate-text', methods=['POST'])
def generate_text():
    try:
        print("=" * 50)
        print("📚 DÉBUT generate_text")
        
        data = request.get_json()
        print(f"📥 Data reçue : {data}")
        
        user_prompt = data.get('prompt', '')
        level = data.get('level', 2)
        langue_user = data.get('langue_user', 'Español')
        
        print(f"📝 Génération de texte niveau {level} pour {langue_user}")
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY manquant")
        
        prompt = f"""Génère un texte pédagogique en français pour des élèves {langue_user} de niveau {level}.

Sujet : {user_prompt}

Le texte doit :
- Être adapté au niveau {level} (1=débutant, 6=avancé)
- Faire environ 100 mots
- Utiliser un vocabulaire approprié au niveau
- Être engageant et pédagogique

Réponds UNIQUEMENT avec le texte, sans introduction ni conclusion méta.
"""
        
        print("📤 Appel à l'API Anthropic...")
        
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 2000,
                'messages': [{'role': 'user', 'content': prompt}]
            }
        )
        
        print(f"📊 Status code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ Erreur API : {response.text}")
            return jsonify({"status": "error", "message": f"Erreur API: {response.status_code}"}), 500
        
        claude_response = response.json()
        text_content = claude_response['content'][0]['text'].strip()
        
        print(f"✅ Texte généré ({len(text_content)} caractères)")
        print("=" * 50)
        
        return jsonify({"status": "ok", "text": text_content}), 200
        
    except Exception as e:
        print("=" * 50)
        print(f"❌ ERREUR : {e}")
        import traceback
        traceback.print_exc()
        print("=" * 50)
        return jsonify({"status": "error", "message": str(e)}), 500
# Configuration Cloudinary
cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
)
print("Connexion à Cloudinary réussie !")




# Fonction pour générer une image avec Stability.ai
def generate_image(prompt, output_file, reference_image_path=None, strength=0.8):
    if not STABILITY_API_KEY:
        print("⚠️ Aucun STABILITY_API_KEY fourni, génération d'image ignorée.")
        return None

    aspect_ratio = "16:9"  # Définit ici le ratio d'aspect


    # Affiche les données qui seront envoyées (pour debug)
    print("Données envoyées :")
    print({
        "prompt": prompt,
        "output_format": "jpeg",
        "strength": strength,
        "aspect_ratio": aspect_ratio,  # Ratio souhaité
    })

    files = {}
    if reference_image_path:
        try:
            with open(reference_image_path, "rb") as img_file:
                image_data = img_file.read()
                files["image"] = ("reference.png", image_data, "image/png")
        except FileNotFoundError:
            print(f"Erreur : Le fichier image {reference_image_path} est introuvable. L'appel sera effectué sans image de référence.")

    if not files:
        files = {"none": ''}

    response = requests.post(
        STABILITY_ENDPOINT,
        headers={
            "authorization": f"Bearer {STABILITY_API_KEY}",
            "accept": "image/*",
        },
        files=files,
        data={
            "prompt": prompt,
            "negative_prompt": "",
            "output_format": "jpeg",
            "aspect_ratio":aspect_ratio,


        },
    )
   
    # Vérification de la réponse
    if response.status_code == 200 and response.content:
        print(f"Statut HTTP : {response.status_code}")
        print("Réponse brute de l'API :", response.content[:100])  
        with open(output_file, 'wb') as file:
            file.write(response.content)
        print(f"L'image a été générée et enregistrée sous : {output_file}")
        return output_file
    elif response.content:
        print(f"Réponse inattendue : {response.text}")
    else:
        print(f"Erreur {response.status_code} : Aucune donnée reçue.")

    return None




# Fonction pour uploader l'image dans Cloudinary (arrête le script si ça échoue)
def upload_image_to_cloudinary(image_path, cloudinary_folder="trivia_images"):
    # public_id = nom du fichier SANS extension (pas de répétition de dossier)
    public_id = os.path.splitext(os.path.basename(image_path))[0]

    response = cloudinary.uploader.upload(
        image_path,
        folder=cloudinary_folder,   # ex. "trivia_images"
        public_id=public_id,        # ex. "furioso_1"
        resource_type="image"
    )

    print(f"Image uploadée sur Cloudinary : {response['secure_url']}")
    return response["secure_url"]


# Chemin local de l'image de référence (si tu l'utilises ailleurs)
reference_image_path = STABILITY_REFERENCE_IMAGE_PATH

# Dossier local temporaire pour stocker les fichiers audio avant l'upload 
audio_folder = os.path.join(SCRIPT_DIR, "temp_audio")
os.makedirs(audio_folder, exist_ok=True)

print ("Dossier local temporaire défini")


print("import librairie G to speech et os réussi")

# Fonction pour générer et sauvegarder un fichier audio
def generate_audio(text, language_code, file_name):
    try:
        # 1. Afficher les paramètres d'entrée
        print(f"Generating audio for text: '{text}', Language code: {language_code}, File name: {file_name}")

        synthesis_input = texttospeech.SynthesisInput(text=text)

        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL)

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3)

        print("Calling Google Text-to-Speech API...")

        response = tts_client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config)

        if not response.audio_content:
            print(f"❌ Réponse vide pour le texte : '{text}' avec code langue : {language_code}")
            return None

        print(f"Received {len(response.audio_content)} bytes of audio data from API.")

        audio_path = os.path.join(audio_folder, f"{file_name}.mp3")
        counter = 1
        while os.path.exists(audio_path):
            audio_path = os.path.join(audio_folder, f"{file_name}_{counter}.mp3")
            counter += 1

        print(f"Saving audio file to: {audio_path}")

        with open(audio_path, "wb") as out:
            out.write(response.audio_content)

        print(f"Audio content written to file {audio_path}")
        return audio_path

    except Exception as e:
        print(f"🔥 Erreur dans generate_audio() pour '{text}' : {e}")
        return None




import re

def sanitize_filename(filename):
    """ Nettoie le nom de fichier pour éviter les erreurs Cloudinary """
    filename = filename.lower().replace(" ", "_")  # Remplace les espaces par _
    filename = re.sub(r'[^a-zA-Z0-9_\-]', '', filename)  # Supprime caractères spéciaux
    return filename


def upload_to_cloudinary(file_path, cloudinary_folder_path="trivias_audios"):
    """
    Upload a file to Cloudinary under a specific folder.

    Args:
        file_path (str): Path to the local file to upload.
        cloudinary_folder_path (str): The folder in Cloudinary where the file will be uploaded.

    Returns:
        tuple: (public_url, embed_url)
    """
    # Extraire le nom du fichier sans extension
    file_name = os.path.splitext(os.path.basename(file_path))[0]
    
    file_name_clean = sanitize_filename(file_name)  # Nettoyage du nom
    public_id = file_name_clean


    # Uploader le fichier sur Cloudinary
    response = cloudinary.uploader.upload(
        file_path, 
        folder=cloudinary_folder_path,
        resource_type="auto",  # Supporte les fichiers audio
        public_id=public_id    # Spécifie le chemin dans Cloudinary
    )

    # Récupérer les URLs générées
    public_url = response["secure_url"]  # URL publique du fichier
    embed_url = response.get("url", public_url)  # URL intégrée (identique dans la plupart des cas)

    print(f"Fichier uploadé sur Cloudinary : {public_url}")
    print(f"URL intégrée : {embed_url}")

    return public_url, embed_url



print("📤 Début de l'envoi vers Firestore...")


def col(row, key, default=""):
    return row.get(key, default)


def validate_and_split_answers(answers_str):
    if not answers_str or not isinstance(answers_str, str):
        return []
    
    answers_str = answers_str.strip()
    
    # Simple : si pas de barres verticales = erreur
    if '|' not in answers_str:
        print(f"❌ ERREUR FORMAT: Aucune barre verticale détectée")
        print(f"   Données reçues: '{answers_str}'")
        print(f"   Format attendu: 'réponse1 | réponse2 | réponse3'")
        raise ValueError(f"Format incorrect pour suggested_answers: {answers_str}")
    
    # Split normal avec barres verticales
    result = [answer.strip() for answer in re.split(r'\s*\|\s*', answers_str) if answer.strip()]
    
    # Validation supplémentaire
    if len(result) < 2:
        print(f"⚠️ ATTENTION: Seulement {len(result)} réponse(s) trouvée(s) dans: '{answers_str}'")
    
    return result

def run_main_script():
    global data_in_memory
    data = data_in_memory

    print("📤 Début du traitement des questions...")

    if not data_in_memory:
        print("❌ Aucune donnée en mémoire. Envoie d'abord le JSON depuis le back office.")
        return

    for i, row in enumerate(data, start=1):
        print(f"👉 Type de row reçu : {type(row)}")
        index_tts = col(row, "index_tts", 8)
        text = row["mot"] if str(index_tts) == "8" else row["correct_answer"]
        language_code = col(row, "accent_tts", "fr-FR")
        file_name = text.replace(" ", "_")


        audio_path            = generate_audio(text, language_code, file_name)
        public_url, embed_url = upload_to_cloudinary(audio_path)

        cloudinary_url = ""
        if col(row, "image_yesno").lower() == "yes":
            prompt   = col(row, "image_prompt")
            img_name = f"{file_name}_{i}.jpeg"
            img_path = generate_image(prompt, img_name, reference_image_path, 0.8)
            if img_path:
                cloudinary_url = upload_image_to_cloudinary(img_path)

        question_doc = {
            "category_q2"      : col(row, "category_q2"),
            "q2_content"       : col(row, "q2_content"),
            "question_level"   : col(row, "question_level"),
            "correct_answer"   : col(row, "correct_answer"),
            "suggested_answers": validate_and_split_answers(col(row, "suggested_answers")),
            "words_count"      : col(row, "words_count"),
            "langue_to_learn"  : col(row, "langue_to_learn"),
            "langue_user"      : col(row, "langue_user"),
            "mot"              : col(row, "mot"),
            "texte_explicatif" : col(row, "texte_explicatif"),
            "sound_link"       : public_url,
            "dl_link"          : embed_url,
            "accent_tts"       : col(row, "accent_tts"),
            "index_tts"        : col(row, "index_tts"),
            "image_yesno"      : col(row, "image_yesno"),
            "image_link"       : cloudinary_url,
            "image_prompt"     : col(row, "image_prompt"),
            "type"             : col(row, "type"),
            "q2_users"         : ["paulmkmaurice@gmail.com"],
            "random"           : random.random(),
            "createdAt"        : firestore.SERVER_TIMESTAMP,
        }

        db.collection("question_test").add(question_doc)
        print(f"✅ Question {i} envoyée dans Firestore")

    print("✅ Toutes les questions ont été traitées.")
    # on renvoie un dictionnaire pour pouvoir l’envoyer en JSON
    return {"count": i}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8091))
    app.run(host='0.0.0.0', port=port, debug=False)

