# Déploiement de `autodropbox.py` sur Render

## 1. Préparer le dépôt Git
- Vérifie que les fichiers suivants sont présents dans `scriptauto/` : `autodropbox.py`, `requirements.txt`, `Procfile`, `.env.example`, `README_DEPLOY.md`.
- Copie le contenu de `.env.example` dans un nouveau fichier `.env` local (optionnel) et renseigne les valeurs pour tester en local.
- Ajoute et commite les fichiers :
  ```bash
  git add scriptauto/
  git commit -m "Prepare autodropbox for Render"
  git push origin main
  ```

## 2. Créer le service Web sur Render
1. Connecte ton compte Render à GitHub (si ce n’est pas déjà fait).
2. Clique sur **New +** → **Web Service**.
3. Choisis le dépôt Git qui contient `scriptauto/autodropbox.py`.
4. Paramètres recommandés :
   - **Environment** : `Python 3`
   - **Build Command** : `pip install -r scriptauto/requirements.txt`
   - **Start Command** : `cd scriptauto && gunicorn autodropbox:app`
   - **Region** : Choisis la plus proche de tes utilisateurs (ex. `Frankfurt` pour l’Europe).
5. Clique sur **Create Web Service**.

## 3. Variables d’environnement à configurer sur Render
Dans l’onglet **Environment** du service Render, ajoute les variables suivantes (prises depuis `.env.example`) :

| Variable | Description |
| --- | --- |
| `ANTHROPIC_API_KEY` | Clé API Anthropic pour les générations Claude |
| `CLOUDINARY_CLOUD_NAME` | Nom du cloud Cloudinary |
| `CLOUDINARY_API_KEY` | Clé API Cloudinary |
| `CLOUDINARY_API_SECRET` | Secret API Cloudinary |
| `STABILITY_API_KEY` | Clé API Stability.ai (si tu génères des images) |
| `STABILITY_ENDPOINT` | Endpoint Stability.ai (optionnel, valeur par défaut fournie) |
| `STABILITY_REFERENCE_IMAGE_PATH` | (Optionnel) Chemin vers une image de référence si tu en utilises une |
| `FIREBASE_CREDENTIALS_JSON` | Contenu JSON du compte de service Firebase/Google Cloud (recommandé) |
| `FIREBASE_CREDENTIALS_PATH` | Chemin vers le JSON si tu préfères stocker le fichier dans Render (laisser vide si tu utilises `FIREBASE_CREDENTIALS_JSON`) |

> ℹ️ Tu peux coller directement le JSON complet de ton compte de service dans `FIREBASE_CREDENTIALS_JSON`. Le script créera automatiquement un fichier temporaire à partir de cette valeur.

## 4. Déployer et tester
1. Une fois les variables renseignées, redéploie le service si nécessaire (`Deploy latest commit`).
2. Render fournit une URL publique du type `https://autodropbox.onrender.com`. C’est cette URL que tu dois utiliser dans l’application Flutter (via `API_BASE_URL`).
3. Teste les endpoints :
   - `POST /generate-questions`
   - `POST /generate-text`
   - `POST /upload-json`
   - `GET /start-script`
   Utilise `curl` ou un outil type Postman/Insomnia pour valider les réponses.

## 5. Déploiements ultérieurs
- Chaque `git push` sur la branche choisie déclenchera un nouveau déploiement.
- Pour ajouter une variable d’environnement ou mettre à jour un secret, va dans l’onglet **Environment** puis redeploie.

## 6. Points d’attention
- Render met en veille les services gratuits après quelques minutes d’inactivité. Prévois un plan payant si tu veux un service 24/7 sans cold start.
- Pense à sécuriser l’accès à l’API (clé partagée, Basic Auth, etc.) si elle est exposée publiquement.
- Surveille l’usage des API (Anthropic, Cloudinary, Stability.ai) pour éviter les dépassements de quotas.

