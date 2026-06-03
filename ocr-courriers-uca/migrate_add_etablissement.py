"""
Migration : ajouter la colonne 'etablissement' à la table courriers.

Usage :
    python migrate_add_etablissement.py

Ce script est IDEMPOTENT : il ne fait rien si la colonne existe déjà.
À exécuter UNE FOIS après la mise à jour du code.
"""
import sqlite3
import os
import sys

# Ajouter la racine au PYTHONPATH pour charger config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app.config import settings
    DATABASE_URL = settings.DATABASE_URL
except Exception:
    DATABASE_URL = f"sqlite:///{os.path.join(os.path.dirname(__file__), 'courriers.db')}"

# Extraire le chemin de la DB depuis l'URL
if DATABASE_URL.startswith("sqlite:///"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
else:
    print(f"Migration automatique uniquement pour SQLite. DATABASE_URL={DATABASE_URL}")
    sys.exit(1)

if not os.path.exists(db_path):
    print(f"Base de données introuvable : {db_path}")
    print("→ La colonne sera créée automatiquement au prochain démarrage via init_db().")
    sys.exit(0)

print(f"Base de données trouvée : {db_path}")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Vérifier si la colonne existe déjà
cur.execute("PRAGMA table_info(courriers)")
columns = [row[1] for row in cur.fetchall()]

if "etablissement" in columns:
    print("✓ La colonne 'etablissement' existe déjà — rien à faire.")
else:
    print("→ Ajout de la colonne 'etablissement'...")
    cur.execute("ALTER TABLE courriers ADD COLUMN etablissement VARCHAR(100)")
    conn.commit()
    print("✓ Colonne ajoutée avec succès.")

conn.close()
print("Terminé.")
