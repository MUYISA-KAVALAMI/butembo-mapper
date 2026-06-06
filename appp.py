from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
import sqlite3
import hashlib
import json
import random
import string
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'butembo_mapper_secret_key_2024'

# ============ INITIALISATION BASE DE DONNÉES ============
def init_db():
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    # Table des utilisateurs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table des lieux (points d'intérêt)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            categorie TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            adresse TEXT,
            telephone TEXT,
            website TEXT,
            description TEXT,
            user_id INTEGER,
            status TEXT DEFAULT 'approved',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Table pour les positions en temps réel
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            speed REAL DEFAULT 0,
            altitude REAL DEFAULT 0,
            accuracy REAL DEFAULT 0,
            mode TEXT DEFAULT 'person',
            is_sharing INTEGER DEFAULT 0,
            last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Table pour les codes de partage
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS share_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Base de données initialisée avec toutes les tables")

# ============ FONCTIONS UTILITAIRES ============
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Non authentifié'}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Non authentifié'}), 401
        if session.get('role') != 'admin':
            return jsonify({'error': 'Accès non autorisé'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ============ PAGES HTML ============
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/admin')
def admin_page():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    return render_template('admin.html')

# ============ ROUTES AUTHENTIFICATION ============

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if not username or not email or not password:
        return jsonify({'error': 'Tous les champs sont requis'}), 400
    
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    # Vérifier si l'utilisateur existe
    cursor.execute('SELECT id FROM users WHERE username = ? OR email = ?', (username, email))
    if cursor.fetchone():
        conn.close()
        return jsonify({'error': 'Nom d\'utilisateur ou email déjà utilisé'}), 400
    
    # Déterminer le rôle (le premier utilisateur est admin)
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    role = 'admin' if count == 0 else 'user'
    
    # Créer l'utilisateur
    hashed_password = hash_password(password)
    cursor.execute(
        'INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)',
        (username, email, hashed_password, role)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({
        'message': 'Inscription réussie',
        'user': {
            'id': user_id,
            'username': username,
            'email': email,
            'role': role
        }
    }), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Tous les champs sont requis'}), 400
    
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    hashed_password = hash_password(password)
    cursor.execute(
        'SELECT id, username, email, role FROM users WHERE (username = ? OR email = ?) AND password = ?',
        (username, username, hashed_password)
    )
    user = cursor.fetchone()
    conn.close()
    
    if user:
        session['user_id'] = user[0]
        session['username'] = user[1]
        session['role'] = user[3]
        
        return jsonify({
            'message': 'Connexion réussie',
            'user': {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'role': user[3]
            }
        }), 200
    else:
        return jsonify({'error': 'Identifiants invalides'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Déconnexion réussie'}), 200

@app.route('/api/me', methods=['GET'])
def get_me():
    if 'user_id' not in session:
        return jsonify({'error': 'Non authentifié'}), 401
    
    return jsonify({
        'id': session['user_id'],
        'username': session['username'],
        'role': session['role']
    }), 200

# ============ ROUTES POINTS D'INTÉRÊT ============

@app.route('/api/points', methods=['GET'])
def get_points():
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT p.*, u.username as contributeur 
        FROM points p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.status = 'approved'
        ORDER BY p.created_at DESC
    ''')
    
    points = []
    for row in cursor.fetchall():
        points.append({
            'id': row[0],
            'nom': row[1],
            'categorie': row[2],
            'latitude': row[3],
            'longitude': row[4],
            'adresse': row[5],
            'telephone': row[6],
            'website': row[7],
            'description': row[8],
            'user_id': row[9],
            'status': row[10],
            'created_at': row[11],
            'contributeur': row[12] if len(row) > 12 else None
        })
    
    conn.close()
    return jsonify(points), 200

@app.route('/api/points', methods=['POST'])
@login_required
def add_point():
    data = request.json
    
    nom = data.get('nom')
    categorie = data.get('categorie')
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    adresse = data.get('adresse', '')
    telephone = data.get('telephone', '')
    website = data.get('website', '')
    description = data.get('description', '')
    
    if not all([nom, categorie, latitude, longitude]):
        return jsonify({'error': 'Nom, catégorie et coordonnées sont requis'}), 400
    
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO points (nom, categorie, latitude, longitude, adresse, telephone, website, description, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (nom, categorie, latitude, longitude, adresse, telephone, website, description, session['user_id']))
    
    point_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({
        'id': point_id,
        'message': 'Lieu ajouté avec succès'
    }), 201

@app.route('/api/points/<int:point_id>', methods=['DELETE'])
@login_required
def delete_point(point_id):
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    # Vérifier si l'utilisateur est admin ou propriétaire
    if session.get('role') != 'admin':
        cursor.execute('SELECT user_id FROM points WHERE id = ?', (point_id,))
        point = cursor.fetchone()
        if not point or point[0] != session['user_id']:
            conn.close()
            return jsonify({'error': 'Non autorisé'}), 403
    
    cursor.execute('DELETE FROM points WHERE id = ?', (point_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Lieu supprimé'}), 200

# ============ ROUTES LOCALISATION EN TEMPS RÉEL ============

@app.route('/api/update-location', methods=['POST'])
@login_required
def update_location():
    data = request.json
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    mode = data.get('mode', 'person')
    speed = data.get('speed', 0)
    altitude = data.get('altitude', 0)
    accuracy = data.get('accuracy', 0)
    is_sharing = data.get('is_sharing', 1)
    
    if latitude is None or longitude is None:
        return jsonify({'error': 'Coordonnées requises'}), 400
    
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO user_locations 
        (user_id, latitude, longitude, speed, altitude, accuracy, mode, is_sharing, last_update)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (session['user_id'], latitude, longitude, speed, altitude, accuracy, mode, is_sharing))
    
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Position mise à jour'}), 200

@app.route('/api/get-location/<int:target_user_id>', methods=['GET'])
@login_required
def get_location(target_user_id):
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT u.username, ul.latitude, ul.longitude, ul.speed, ul.mode, ul.last_update, ul.is_sharing
        FROM user_locations ul
        JOIN users u ON u.id = ul.user_id
        WHERE ul.user_id = ? AND ul.is_sharing = 1
    ''', (target_user_id,))
    
    location = cursor.fetchone()
    conn.close()
    
    if not location:
        return jsonify({'error': 'Utilisateur ne partage pas sa position'}), 404
    
    return jsonify({
        'username': location[0],
        'latitude': location[1],
        'longitude': location[2],
        'speed': location[3],
        'mode': location[4],
        'last_update': location[5]
    }), 200

@app.route('/api/active-users', methods=['GET'])
@login_required
def get_active_users():
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    # Utilisateurs actifs dans les dernières 30 secondes
    threshold = datetime.now() - timedelta(seconds=30)
    
    cursor.execute('''
        SELECT u.id, u.username, ul.latitude, ul.longitude, ul.mode, ul.last_update
        FROM user_locations ul
        JOIN users u ON u.id = ul.user_id
        WHERE ul.is_sharing = 1 
        AND ul.last_update > ?
        AND ul.user_id != ?
    ''', (threshold, session['user_id']))
    
    users = []
    for row in cursor.fetchall():
        users.append({
            'id': row[0],
            'username': row[1],
            'latitude': row[2],
            'longitude': row[3],
            'mode': row[4],
            'last_update': row[5]
        })
    
    conn.close()
    return jsonify(users), 200

@app.route('/api/generate-share-code', methods=['POST'])
@login_required
def generate_share_code():
    # Générer un code unique
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    expires_at = datetime.now() + timedelta(hours=1)
    
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    # Supprimer les anciens codes
    cursor.execute('DELETE FROM share_codes WHERE expires_at < ?', (datetime.now(),))
    
    cursor.execute('''
        INSERT INTO share_codes (user_id, code, expires_at)
        VALUES (?, ?, ?)
    ''', (session['user_id'], code, expires_at))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'code': code,
        'expires_at': expires_at.isoformat()
    }), 200

@app.route('/api/share-code-location/<code>', methods=['GET'])
@login_required
def get_share_code_location(code):
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT sc.user_id, u.username, ul.latitude, ul.longitude, ul.mode, ul.last_update
        FROM share_codes sc
        JOIN users u ON u.id = sc.user_id
        LEFT JOIN user_locations ul ON ul.user_id = sc.user_id
        WHERE sc.code = ? AND sc.expires_at > ?
    ''', (code, datetime.now()))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return jsonify({'error': 'Code invalide ou expiré'}), 404
    
    if not result[3] or not result[4]:
        return jsonify({'error': 'Utilisateur non localisé'}), 404
    
    return jsonify({
        'user_id': result[0],
        'username': result[1],
        'latitude': result[2],
        'longitude': result[3],
        'mode': result[4],
        'last_update': result[5]
    }), 200

@app.route('/api/stop-sharing', methods=['POST'])
@login_required
def stop_sharing():
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE user_locations SET is_sharing = 0 WHERE user_id = ?
    ''', (session['user_id'],))
    
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Partage désactivé'}), 200

# ============ ROUTES STATISTIQUES ============

@app.route('/api/statistics', methods=['GET'])
def get_statistics():
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM points')
    total_points = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    # Compter par catégorie
    cursor.execute('SELECT categorie, COUNT(*) FROM points GROUP BY categorie')
    categories = {}
    for row in cursor.fetchall():
        categories[row[0]] = row[1]
    
    # Utilisateurs actifs (localisation)
    threshold = datetime.now() - timedelta(seconds=30)
    cursor.execute('SELECT COUNT(*) FROM user_locations WHERE is_sharing = 1 AND last_update > ?', (threshold,))
    active_users = cursor.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'total_points': total_points,
        'total_users': total_users,
        'active_users': active_users,
        'categories': categories
    }), 200

# ============ ROUTES ADMIN ============

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def get_users():
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, role, created_at FROM users ORDER BY created_at DESC')
    
    users = []
    for row in cursor.fetchall():
        users.append({
            'id': row[0],
            'username': row[1],
            'email': row[2],
            'role': row[3],
            'created_at': row[4]
        })
    
    conn.close()
    return jsonify(users), 200

@app.route('/api/admin/users/<int:user_id>/role', methods=['PUT'])
@admin_required
def update_user_role(user_id):
    data = request.json
    new_role = data.get('role')
    
    if new_role not in ['user', 'admin']:
        return jsonify({'error': 'Rôle invalide'}), 400
    
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Rôle mis à jour'}), 200

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    if user_id == session['user_id']:
        return jsonify({'error': 'Vous ne pouvez pas vous supprimer vous-même'}), 400
    
    conn = sqlite3.connect('butembo.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
    cursor.execute('DELETE FROM user_locations WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Utilisateur supprimé'}), 200

# ============ LANCEMENT DE L'APPLICATION ============
if __name__ == '__main__':
    init_db()
    
    # Afficher les informations de démarrage
    print("\n" + "="*60)
    print("🚀 BUTEMBO MAPPER - APPLICATION COMPLÈTE")
    print("="*60)
    print("📋 Fonctionnalités incluses:")
    print("   ✅ Carte interactive avec OpenStreetMap")
    print("   ✅ Ajout de points d'intérêt")
    print("   ✅ Localisation GPS en temps réel")
    print("   ✅ Partage de position par code QR")
    print("   ✅ Visualisation des autres utilisateurs")
    print("   ✅ Recherche de lieux")
    print("   ✅ Itinéraires")
    print("   ✅ Interface administrateur")
    print("")
    print("📱 Accès depuis l'ordinateur:")
    print("   → http://localhost:5000")
    print("   → http://127.0.0.1:5000")
    print("")
    print("📱 Accès depuis le téléphone (même WiFi):")
    print("   → http://VOTRE_IP:5000")
    print("")
    print("💡 Pour trouver votre IP:")
    print("   Windows: ipconfig | findstr IPv4")
    print("   Mac/Linux: ifconfig | grep inet")
    print("")
    print("🔐 Premier compte créé = ADMINISTRATEUR")
    print("="*60)
    print("")
    
    app.run(debug=True, host='0.0.0.0', port=5000)