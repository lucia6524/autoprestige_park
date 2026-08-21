# AutoPrestige — Site + Backend

## Contenu
- Site vitrine multilingue (FR, EN, DE, IT, ES, PT, RO)
- Catalogue 120 véhicules + pages détail
- Backend FastAPI (auth, panier, commandes, échéancier, livraison)
- Inscription multi-étapes + vérification email OTP

## Démarrage rapide

### 1. Backend
```bash
cd backend
pip install -r requirements.txt

# Optionnel : envoi réel des emails
cp .env.example .env
# Édite .env avec ton Gmail + mot de passe d'application

python run.py
# API sur http://127.0.0.1:8000
```

### 2. Frontend
Ouvre les fichiers HTML via un serveur local :
```bash
# Depuis le dossier autoprestige/
python3 -m http.server 5500
# Puis http://localhost:5500
```

## Pages importantes
| Page | URL |
|------|-----|
| Accueil | index.html |
| Catalogue | vehicules.html |
| Détail véhicule | vehicule.html?id=1 |
| Inscription | inscription.html |
| Connexion | connexion.html |
| Espace compte | compte.html |

## Auth
1. Inscription en 4 étapes (nom → email/tél → salaire → code email)
2. Le code OTP est envoyé par email (ou affiché en console si SMTP non configuré)
3. Après validation → espace compte (panier, commandes, livraison)

## Gmail SMTP
1. Active la validation en 2 étapes Google
2. Crée un mot de passe d'application : https://myaccount.google.com/apppasswords
3. Remplis `backend/.env` avec SMTP_USER et SMTP_PASSWORD
