import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, login_user, LoginManager, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.sql import func, or_, and_
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'vetrico-v27-dev')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vetrico.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB

UPLOAD_FOLDER = os.path.join('static', 'uploads')
AVATAR_FOLDER = os.path.join('static', 'avatars')
for _f in [UPLOAD_FOLDER, AVATAR_FOLDER]:
    os.makedirs(_f, exist_ok=True)

ALLOWED_VIDEO = {'mp4', 'mov', 'webm'}
ALLOWED_IMG   = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
BAD_WORDS = []          # istediğin kelimeleri buraya ekle

online_users = {}       # {user_id: set(session_ids)}

db           = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
socketio     = SocketIO(app, cors_allowed_origins='*', manage_session=False)

# ─────────────────────────── BADGES ───────────────────────────
BADGES = {
    'verified': {
        'label': 'Doğrulanmış',
        'svg': '<svg viewBox="0 0 22 22" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="10" fill="#1D9BF0"/><path d="M7 11.5L9.5 14L15 8.5" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>'
    },
    'king': {
        'label': 'Kral',
        'svg': '<svg viewBox="0 0 22 22" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="10" fill="#F59E0B"/><path d="M7 15.5H15" stroke="white" stroke-width="1.4" stroke-linecap="round"/><path d="M7.5 15L9 10.5L11 13L13 10.5L14.5 15" fill="white"/><circle cx="7" cy="9.5" r="1.2" fill="white"/><circle cx="11" cy="7.5" r="1.2" fill="white"/><circle cx="15" cy="9.5" r="1.2" fill="white"/></svg>'
    },
    'star': {
        'label': 'Yıldız VIP',
        'svg': '<svg viewBox="0 0 22 22" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="10" fill="#8B5CF6"/><path d="M11 6L12.5 9.5H16.5L13.5 11.8L14.5 15.5L11 13.5L7.5 15.5L8.5 11.8L5.5 9.5H9.5L11 6Z" fill="white"/></svg>'
    },
    'fire': {
        'label': 'Trend Yaratıcı',
        'svg': '<svg viewBox="0 0 22 22" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="10" fill="#F97316"/><path d="M11 5C11 5 15.5 8 15.5 12C15.5 14.5 13.5 16.5 11 16.5C8.5 16.5 6.5 14.5 6.5 12C6.5 10 8 8.5 8 8.5C8 8.5 8 10 9.5 11C9.5 11 8.5 8 11 5Z" fill="white"/></svg>'
    },
    'diamond': {
        'label': 'Elmas Üye',
        'svg': '<svg viewBox="0 0 22 22" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="10" fill="#0891B2"/><path d="M7 11L11 6.5L15 11L11 17L7 11Z" fill="white" opacity="0.95"/><line x1="7" y1="11" x2="15" y2="11" stroke="#0891B2" stroke-width="0.8"/><line x1="9" y1="11" x2="11" y2="17" stroke="#0891B2" stroke-width="0.7"/><line x1="13" y1="11" x2="11" y2="17" stroke="#0891B2" stroke-width="0.7"/></svg>'
    },
    'developer': {
        'label': 'Geliştirici',
        'svg': '<svg viewBox="0 0 22 22" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="10" fill="#1E3A8A"/><path d="M8.5 8.5L6 11L8.5 13.5M13.5 8.5L16 11L13.5 13.5" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/><line x1="12.5" y1="7.5" x2="9.5" y2="14.5" stroke="white" stroke-width="1.5" stroke-linecap="round"/></svg>'
    },
    'music': {
        'label': 'Müzisyen',
        'svg': '<svg viewBox="0 0 22 22" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="10" fill="#DB2777"/><path d="M13.5 8V13.5" stroke="white" stroke-width="1.8" stroke-linecap="round" fill="none"/><path d="M13.5 8L16.5 7V9.5L13.5 10.5V8Z" fill="white"/><circle cx="11.5" cy="14" r="2" fill="white"/></svg>'
    },
    'gaming': {
        'label': 'Pro Oyuncu',
        'svg': '<svg viewBox="0 0 22 22" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="10" fill="#16A34A"/><rect x="6" y="8.5" width="10" height="6" rx="2" fill="white"/><line x1="9.5" y1="10" x2="9.5" y2="13" stroke="#16A34A" stroke-width="1.3" stroke-linecap="round"/><line x1="8" y1="11.5" x2="11" y2="11.5" stroke="#16A34A" stroke-width="1.3" stroke-linecap="round"/><circle cx="13.5" cy="10.5" r="0.8" fill="#16A34A"/><circle cx="15" cy="12" r="0.8" fill="#16A34A"/></svg>'
    },
    'shield': {
        'label': 'Moderatör',
        'svg': '<svg viewBox="0 0 22 22" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="10" fill="#DC2626"/><path d="M11 5.5L16.5 8V11.5C16.5 14.5 14 16.8 11 17.5C8 16.8 5.5 14.5 5.5 11.5V8L11 5.5Z" fill="white" opacity="0.9"/><path d="M9 11.5L10.5 13L14 9" stroke="#DC2626" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>'
    },
    'camera': {
        'label': 'İçerik Üreticisi',
        'svg': '<svg viewBox="0 0 22 22" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="10" fill="#6B7280"/><rect x="5.5" y="9" width="11" height="7.5" rx="1.5" fill="white"/><circle cx="11" cy="12.8" r="2.2" fill="#6B7280"/><path d="M9.5 9L10.5 7.5H13.5L14.5 9" fill="white"/></svg>'
    }
}

# ─────────────────────────── MODELS ───────────────────────────
followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)
likes = db.Table('likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('video_id', db.Integer, db.ForeignKey('video.id', ondelete='CASCADE'))
)
bookmarks = db.Table('bookmarks',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('video_id', db.Integer, db.ForeignKey('video.id', ondelete='CASCADE'))
)
comment_likes = db.Table('comment_likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('comment_id', db.Integer, db.ForeignKey('comment.id', ondelete='CASCADE'))
)

class User(UserMixin, db.Model):
    id                  = db.Column(db.Integer, primary_key=True)
    username            = db.Column(db.String(150), unique=True, nullable=False)
    password            = db.Column(db.String(300), nullable=False)
    bio                 = db.Column(db.String(250), default='Vetrico dünyasına hoş geldiniz!')
    avatar              = db.Column(db.String(300), nullable=True)
    coins               = db.Column(db.Integer, default=50)
    is_verified         = db.Column(db.Boolean, default=False)
    verification_status = db.Column(db.String(20), default='none')  # none / pending / approved / rejected
    badge_key           = db.Column(db.String(20), nullable=True)
    is_admin            = db.Column(db.Boolean, default=False)
    is_super_admin      = db.Column(db.Boolean, default=False)
    perm_ban_user       = db.Column(db.Boolean, default=False)
    perm_delete_video   = db.Column(db.Boolean, default=False)
    perm_verify_user    = db.Column(db.Boolean, default=False)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)

    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers_list', lazy='dynamic'), lazy='dynamic'
    )
    bookmarked_videos = db.relationship('Video', secondary=bookmarks,
        backref=db.backref('bookmarked_by', lazy='dynamic'))
    notifications = db.relationship('Notification', backref='recipient',
        foreign_keys='Notification.recipient_id', lazy='dynamic', cascade='all, delete-orphan')

    def is_following(self, user):
        return self.followed.filter(followers.c.followed_id == user.id).count() > 0
    def follow(self, user):
        if not self.is_following(user): self.followed.append(user)
    def unfollow(self, user):
        if self.is_following(user): self.followed.remove(user)

class Video(db.Model):
    id                = db.Column(db.Integer, primary_key=True)
    filename          = db.Column(db.String(500), nullable=False)
    user_id           = db.Column(db.Integer, db.ForeignKey('user.id'))
    caption           = db.Column(db.String(500))
    category          = db.Column(db.String(50), default='Genel')
    views             = db.Column(db.Integer, default=0)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    moderation_status = db.Column(db.String(20), default='approved')
    user      = db.relationship('User', backref='videos')
    liked_by  = db.relationship('User', secondary=likes, backref=db.backref('liked_videos', lazy='dynamic'))
    comments  = db.relationship('Comment', backref='video', cascade='all, delete-orphan', lazy='dynamic')
    reports   = db.relationship('Report',  backref='video', cascade='all, delete-orphan', lazy='dynamic')

class Comment(db.Model):
    id                  = db.Column(db.Integer, primary_key=True)
    text                = db.Column(db.String(500), nullable=False)
    user_id             = db.Column(db.Integer, db.ForeignKey('user.id'))
    video_id            = db.Column(db.Integer, db.ForeignKey('video.id', ondelete='CASCADE'))
    parent_id           = db.Column(db.Integer, db.ForeignKey('comment.id', ondelete='CASCADE'), nullable=True)
    is_liked_by_creator = db.Column(db.Boolean, default=False)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    user     = db.relationship('User')
    replies  = db.relationship('Comment',
        backref=db.backref('parent', remote_side=[id]),
        cascade='all, delete-orphan', lazy='dynamic')
    liked_by = db.relationship('User', secondary=comment_likes,
        backref=db.backref('liked_comments', lazy='dynamic'))

class Notification(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    sender_id    = db.Column(db.Integer, db.ForeignKey('user.id'))
    type         = db.Column(db.String(20))
    post_id      = db.Column(db.Integer, nullable=True)
    amount       = db.Column(db.Integer, nullable=True)
    is_read      = db.Column(db.Boolean, default=False)
    timestamp    = db.Column(db.DateTime, default=datetime.utcnow)
    sender       = db.relationship('User', foreign_keys=[sender_id])

class Message(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    sender_id    = db.Column(db.Integer, db.ForeignKey('user.id'))
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    body         = db.Column(db.String(1000))
    timestamp    = db.Column(db.DateTime, default=datetime.utcnow)
    is_read      = db.Column(db.Boolean, default=False)

class Report(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    video_id    = db.Column(db.Integer, db.ForeignKey('video.id', ondelete='CASCADE'))
    reason      = db.Column(db.String(200))
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow)
    reporter    = db.relationship('User')

class AdminLog(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    admin_id    = db.Column(db.Integer, db.ForeignKey('user.id'))
    action_type = db.Column(db.String(30))   # ban / verify / delete_video / make_admin / perm_change
    description = db.Column(db.String(300))
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow)
    admin       = db.relationship('User', foreign_keys=[admin_id])

def add_log(action_type, description):
    """Helper – call inside any admin route."""
    db.session.add(AdminLog(admin_id=current_user.id,
                            action_type=action_type, description=description))

@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

# ─────────────────────────── HELPERS ───────────────────────────
def allowed_video(f): return '.' in f and f.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO
def allowed_img(f):   return '.' in f and f.rsplit('.', 1)[1].lower() in ALLOWED_IMG
def contains_bad_words(t):
    if not t: return False
    return any(w in t.lower() for w in BAD_WORDS)

def push_notif(recipient_id, sender_id, type_, post_id=None, amount=None):
    if recipient_id == sender_id: return
    db.session.add(Notification(
        recipient_id=recipient_id, sender_id=sender_id,
        type=type_, post_id=post_id, amount=amount
    ))

@app.context_processor
def inject_globals():
    notif_count = 0
    if current_user.is_authenticated:
        notif_count = Notification.query.filter_by(
            recipient_id=current_user.id, is_read=False).count()
    return {'unread_notifications': notif_count, 'BADGES': BADGES}

# ─────────────────────────── SOCKET.IO ───────────────────────────
@socketio.on('connect')
def on_connect():
    if current_user.is_authenticated:
        join_room(f'user_{current_user.id}')
        online_users.setdefault(current_user.id, set()).add(request.sid)
        emit('user_status', {'user_id': current_user.id, 'status': 'online'}, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    if current_user.is_authenticated and current_user.id in online_users:
        online_users[current_user.id].discard(request.sid)
        if not online_users[current_user.id]:
            del online_users[current_user.id]
            emit('user_status', {'user_id': current_user.id, 'status': 'offline'}, broadcast=True)

@socketio.on('send_message')
def on_send_message(data):
    body = data.get('body', '').strip()
    if not body or contains_bad_words(body): return
    msg = Message(sender_id=current_user.id, recipient_id=data['recipient_id'], body=body)
    db.session.add(msg); db.session.commit()
    ts = msg.timestamp.strftime('%H:%M')
    emit('receive_message', {'sender_id': current_user.id, 'body': body, 'timestamp': ts},
         room=f"user_{data['recipient_id']}")
    emit('message_sent', {'body': body, 'timestamp': ts})

@socketio.on('typing')
def on_typing(data):
    emit('display_typing', {'sender_id': current_user.id}, room=f"user_{data['recipient_id']}")

@socketio.on('stop_typing')
def on_stop_typing(data):
    emit('hide_typing', {'sender_id': current_user.id}, room=f"user_{data['recipient_id']}")

@socketio.on('send_reaction')
def on_reaction(data):
    emit('animate_reaction', {'emoji': data['emoji']}, broadcast=True)

# ─────────────────────────── AUTH ───────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username', '')).first()
        if user and check_password_hash(user.password, request.form.get('password', '')):
            if user.username == 'tavugeymosu' and not user.is_super_admin:
                user.is_super_admin = user.is_admin = True
                user.perm_ban_user = user.perm_delete_video = user.perm_verify_user = True
                user.is_verified = True; user.badge_key = 'king'
                db.session.commit()
            login_user(user)
            return redirect(url_for('index'))
        flash('Kullanıcı adı veya şifre hatalı!')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('Kullanıcı adı ve şifre zorunlu!')
            return render_template('register.html')
        if User.query.filter_by(username=username).first():
            flash('Bu kullanıcı adı zaten alınmış!')
            return render_template('register.html')
        is_super = (username == 'tavugeymosu')
        u = User(username=username,
                 password=generate_password_hash(password, method='pbkdf2:sha256'),
                 is_admin=is_super, is_super_admin=is_super,
                 perm_ban_user=is_super, perm_delete_video=is_super, perm_verify_user=is_super,
                 is_verified=is_super, badge_key='king' if is_super else None)
        db.session.add(u); db.session.commit()
        login_user(u)
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('index'))

# ─────────────────────────── MAIN PAGES ───────────────────────────
@app.route('/')
def index():
    category = request.args.get('category')
    q = Video.query.filter_by(moderation_status='approved')
    if category: q = q.filter_by(category=category)
    videos = q.order_by(Video.created_at.desc()).limit(30).all()

    stories = []
    if current_user.is_authenticated:
        followed_ids = [u.id for u in current_user.followed]
        if followed_ids:
            seen = set()
            for v in Video.query.filter(Video.user_id.in_(followed_ids),
                                        Video.moderation_status == 'approved'
                                        ).order_by(Video.created_at.desc()).all():
                if v.user_id not in seen:
                    stories.append(v); seen.add(v.user_id)
    return render_template('home.html', videos=videos, stories=stories, active_category=category)

@app.route('/watch/<int:video_id>')
def watch(video_id):
    target = Video.query.get_or_404(video_id)
    if target.moderation_status != 'approved':
        if not (current_user.is_authenticated and current_user.is_admin): abort(404)
    others = Video.query.filter(Video.id != video_id,
                                Video.moderation_status == 'approved'
                               ).order_by(Video.created_at.desc()).limit(15).all()
    return render_template('feed.html', videos=[target] + others)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        file    = request.files.get('file')
        caption = request.form.get('caption', '').strip()
        if not file or not file.filename:
            flash('Lütfen bir video seçin!'); return render_template('upload.html')
        if not allowed_video(file.filename):
            flash('Desteklenmeyen format! MP4, MOV veya WEBM kullanın.')
            return render_template('upload.html')
        if contains_bad_words(caption):
            flash('Açıklamada uygunsuz kelime!'); return render_template('upload.html')
        ext  = file.filename.rsplit('.', 1)[1].lower()
        name = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(UPLOAD_FOLDER, name))
        v = Video(filename=f'/static/uploads/{name}', user_id=current_user.id,
                  caption=caption, category=request.form.get('category', 'Genel'))
        db.session.add(v); db.session.commit()
        flash('✅ Video yüklendi!')
        return redirect(url_for('profile', username=current_user.username))
    return render_template('upload.html')

@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    file = request.files.get('avatar')
    if not file or not file.filename or not allowed_img(file.filename):
        flash('Geçersiz dosya!'); return redirect(url_for('profile', username=current_user.username))
    ext  = file.filename.rsplit('.', 1)[1].lower()
    name = f"av_{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    file.save(os.path.join(AVATAR_FOLDER, name))
    current_user.avatar = f'/static/avatars/{name}'
    db.session.commit()
    flash('Profil fotoğrafı güncellendi!')
    return redirect(url_for('profile', username=current_user.username))

@app.route('/edit/<int:video_id>', methods=['GET', 'POST'])
@login_required
def edit_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.user_id != current_user.id and not current_user.is_admin: abort(403)
    if request.method == 'POST':
        caption = request.form.get('caption', '').strip()
        if contains_bad_words(caption):
            flash('Uygunsuz kelime!'); return render_template('edit_video.html', video=video)
        video.caption  = caption
        video.category = request.form.get('category', video.category)
        db.session.commit(); flash('Güncellendi!')
        return redirect(url_for('profile', username=current_user.username))
    return render_template('edit_video.html', video=video)

@app.route('/delete_video/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.user_id != current_user.id and not current_user.is_admin: abort(403)
    if video.filename.startswith('/static/'):
        p = video.filename.lstrip('/')
        if os.path.exists(p): os.remove(p)
    db.session.delete(video); db.session.commit()
    flash('Video silindi.')
    return redirect(url_for('profile', username=current_user.username))

@app.route('/apply_verification', methods=['POST'])
@login_required
def apply_verification():
    if current_user.verification_status not in ['none', 'rejected']:
        flash('Zaten başvurdunuz.')
    else:
        current_user.verification_status = 'pending'; db.session.commit()
        flash('Başvurunuz alındı!')
    return redirect(url_for('profile', username=current_user.username))

@app.route('/profile/<username>')
def profile(username):
    user       = User.query.filter_by(username=username).first_or_404()
    videos     = Video.query.filter_by(user_id=user.id).order_by(Video.created_at.desc()).all()
    is_following = current_user.is_authenticated and current_user.is_following(user)
    return render_template('profile.html', user=user, videos=videos,
                           bookmarked=user.bookmarked_videos, is_following=is_following)

@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    users, videos = [], []
    if q:
        users  = User.query.filter(User.username.ilike(f'%{q}%')).limit(20).all()
        videos = Video.query.filter(Video.caption.ilike(f'%{q}%'),
                                    Video.moderation_status == 'approved').limit(20).all()
    return render_template('search.html', users=users, videos=videos, query=q)

@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(
        recipient_id=current_user.id).order_by(Notification.timestamp.desc()).limit(50).all()
    for n in notifs: n.is_read = True
    db.session.commit()
    return render_template('notifications.html', notifications=notifs)

@app.route('/messages')
@login_required
def messages():
    all_msgs = Message.query.filter(
        or_(Message.sender_id == current_user.id, Message.recipient_id == current_user.id)
    ).order_by(Message.timestamp.desc()).all()
    convos = {}
    for m in all_msgs:
        oid = m.recipient_id if m.sender_id == current_user.id else m.sender_id
        if oid not in convos:
            ou = User.query.get(oid)
            if ou:
                unread = Message.query.filter_by(sender_id=oid,
                    recipient_id=current_user.id, is_read=False).count()
                convos[oid] = {'user': ou, 'last_msg': m, 'unread': unread,
                               'is_online': oid in online_users}
    return render_template('chat_list.html', conversations=list(convos.values()))

@app.route('/messages/<int:user_id>')
@login_required
def chat_detail(user_id):
    other = User.query.get_or_404(user_id)
    msgs  = Message.query.filter(
        or_(and_(Message.sender_id == current_user.id, Message.recipient_id == user_id),
            and_(Message.sender_id == user_id, Message.recipient_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()
    for m in msgs:
        if m.recipient_id == current_user.id: m.is_read = True
    db.session.commit()
    return render_template('chat_detail.html', other_user=other, messages=msgs,
                           is_online=user_id in online_users)

# ─────────────────────────── ADMIN ───────────────────────────
@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin: abort(403)
    from sqlalchemy import text
    stats = {
        'users':         User.query.count(),
        'admins':        User.query.filter_by(is_admin=True).count(),
        'videos':        Video.query.count(),
        'pending_videos': Video.query.filter_by(moderation_status='pending').count(),
        'likes':         db.session.execute(text('SELECT COUNT(*) FROM likes')).scalar() or 0,
        'reports':       Report.query.count()
    }
    pending      = User.query.filter_by(verification_status='pending').all()
    reports      = Report.query.order_by(Report.timestamp.desc()).all()
    all_users    = User.query.order_by(User.created_at.desc()).limit(200).all() if current_user.is_super_admin else User.query.order_by(User.created_at.desc()).limit(200).all()
    admins       = User.query.filter_by(is_admin=True).all()
    videos       = Video.query.order_by(Video.id.desc()).limit(40).all()
    recent_users = User.query.order_by(User.created_at.desc()).limit(8).all()
    logs         = AdminLog.query.order_by(AdminLog.timestamp.desc()).limit(80).all() if current_user.is_super_admin else []
    return render_template('admin.html', stats=stats, users=all_users, admins=admins,
                           videos=videos, pending_verifications=pending, reports=reports,
                           recent_users=recent_users, logs=logs)

@app.route('/admin/delete_video/<int:vid>')
@login_required
def admin_delete_video(vid):
    if not current_user.is_admin or not current_user.perm_delete_video: abort(403)
    v = Video.query.get_or_404(vid)
    if v.filename.startswith('/static/'):
        p = v.filename.lstrip('/')
        if os.path.exists(p): os.remove(p)
    add_log('delete_video', f"Video silindi: #{vid} (@{v.user.username})")
    db.session.delete(v); db.session.commit(); flash('Video silindi.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<int:uid>')
@login_required
def admin_delete_user(uid):
    if not current_user.is_admin or not current_user.perm_ban_user: abort(403)
    u = User.query.get_or_404(uid)
    if u.username == 'tavugeymosu': abort(403)
    add_log('ban', f"Kullanıcı banlandı: @{u.username}")
    db.session.delete(u); db.session.commit(); flash('Kullanıcı silindi.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/force_verify/<int:uid>', methods=['POST'])
@login_required
def force_verify(uid):
    if not current_user.is_admin or not current_user.perm_verify_user: abort(403)
    u = User.query.get_or_404(uid); badge = request.form.get('badge', '')
    if badge and badge in BADGES:
        u.is_verified = True; u.badge_key = badge; u.verification_status = 'approved'
        push_notif(u.id, current_user.id, 'system_approve')
        add_log('verify', f"Rozet verildi: @{u.username} → {BADGES[badge]['label']}")
        db.session.commit(); flash(f'{BADGES[badge]["label"]} rozeti verildi!')
    else:
        u.is_verified = False; u.badge_key = None; u.verification_status = 'none'
        add_log('verify', f"Rozet kaldırıldı: @{u.username}")
        db.session.commit(); flash('Rozet alındı.')
    return redirect(url_for('profile', username=u.username))

@app.route('/admin/approve_verification/<int:uid>', methods=['POST'])
@login_required
def approve_verification(uid):
    if not current_user.is_admin or not current_user.perm_verify_user: abort(403)
    u = User.query.get_or_404(uid)
    bk = request.form.get('badge', 'verified')
    if bk not in BADGES: bk = 'verified'
    u.is_verified = True; u.verification_status = 'approved'; u.badge_key = bk
    push_notif(u.id, current_user.id, 'system_approve')
    add_log('verify', f"Başvuru onaylandı: @{u.username} → {BADGES[bk]['label']}")
    db.session.commit(); flash('Onaylandı!')
    return redirect(url_for('admin_panel'))

@app.route('/admin/reject_verification/<int:uid>')
@login_required
def reject_verification(uid):
    if not current_user.is_admin or not current_user.perm_verify_user: abort(403)
    u = User.query.get_or_404(uid)
    u.is_verified = False; u.verification_status = 'rejected'; u.badge_key = None
    add_log('verify', f"Başvuru reddedildi: @{u.username}")
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/manage_role/<int:uid>', methods=['POST'])
@login_required
def manage_role(uid):
    if not current_user.is_super_admin: abort(403)
    t = User.query.get_or_404(uid)
    if t.username == 'tavugeymosu': abort(403)
    t.is_admin = True
    t.perm_ban_user     = 'perm_ban'    in request.form
    t.perm_delete_video = 'perm_delete' in request.form
    t.perm_verify_user  = 'perm_verify' in request.form
    add_log('perm_change', f"Yetkiler güncellendi: @{t.username}")
    db.session.commit(); flash('Yetkiler güncellendi.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/remove_admin/<int:uid>')
@login_required
def remove_admin(uid):
    if not current_user.is_super_admin: abort(403)
    t = User.query.get_or_404(uid)
    if t.username == 'tavugeymosu': abort(403)
    add_log('perm_change', f"Admin yetkisi alındı: @{t.username}")
    t.is_admin = t.perm_ban_user = t.perm_delete_video = t.perm_verify_user = False
    db.session.commit(); flash('Admin yetkisi alındı.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/dismiss_report/<int:rid>')
@login_required
def dismiss_report(rid):
    if not current_user.is_admin: abort(403)
    r = Report.query.get_or_404(rid); db.session.delete(r); db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/make_admin_by_name', methods=['POST'])
@login_required
def make_admin_by_name():
    if not current_user.is_super_admin: abort(403)
    data = request.get_json() or {}
    u = User.query.filter_by(username=data.get('username', '')).first()
    if not u: return jsonify({'error': 'Kullanıcı bulunamadı!'})
    if u.username == 'tavugeymosu': return jsonify({'error': 'Bu kullanıcıya dokunulamaz.'})
    u.is_admin          = True
    u.perm_ban_user     = bool(data.get('perm_ban', False))
    u.perm_delete_video = bool(data.get('perm_delete', False))
    u.perm_verify_user  = bool(data.get('perm_verify', False))
    add_log('make_admin', f"Admin yapıldı: @{u.username} (ban={u.perm_ban_user}, del={u.perm_delete_video}, ver={u.perm_verify_user})")
    db.session.commit()
    return jsonify({'message': f'@{u.username} admin yapıldı!'})

@app.route('/admin/api/toggle_perm/<int:uid>', methods=['POST'])
@login_required
def api_toggle_perm(uid):
    if not current_user.is_super_admin: return jsonify({'error': 'Yetkisiz'}), 403
    u = User.query.get_or_404(uid)
    if u.username == 'tavugeymosu': return jsonify({'error': 'Korumalı kullanıcı'}), 403
    data = request.get_json() or {}
    ptype = data.get('type'); val = bool(data.get('value'))
    if ptype == 'ban':      u.perm_ban_user     = val
    elif ptype == 'delete': u.perm_delete_video = val
    elif ptype == 'verify': u.perm_verify_user  = val
    else: return jsonify({'error': 'Geçersiz tür'}), 400
    add_log('perm_change', f"Yetki toggle: @{u.username} {ptype}={val}")
    db.session.commit()
    return jsonify({'ok': True, 'message': 'Kaydedildi'})

@app.route('/admin/api/set_perms/<int:uid>', methods=['POST'])
@login_required
def api_set_perms(uid):
    if not current_user.is_super_admin: return jsonify({'error': 'Yetkisiz'}), 403
    u = User.query.get_or_404(uid)
    if u.username == 'tavugeymosu': return jsonify({'error': 'Korumalı kullanıcı'}), 403
    data = request.get_json() or {}
    u.is_admin          = bool(data.get('is_admin', u.is_admin))
    u.perm_ban_user     = bool(data.get('perm_ban',    u.perm_ban_user))
    u.perm_delete_video = bool(data.get('perm_delete', u.perm_delete_video))
    u.perm_verify_user  = bool(data.get('perm_verify', u.perm_verify_user))
    add_log('perm_change', f"Yetkiler ayarlandı: @{u.username}")
    db.session.commit()
    return jsonify({'message': '✓ Kaydedildi'})

@app.route('/admin/api/assign_badge', methods=['POST'])
@login_required
def api_assign_badge():
    if not current_user.is_admin or not current_user.perm_verify_user:
        return jsonify({'error': 'Yetkisiz'}), 403
    data = request.get_json() or {}
    u = User.query.filter_by(username=data.get('username', '').replace('@', '')).first()
    if not u: return jsonify({'error': 'Kullanıcı bulunamadı!'})
    badge = data.get('badge', '')
    if badge and badge in BADGES:
        u.is_verified = True; u.badge_key = badge; u.verification_status = 'approved'
        push_notif(u.id, current_user.id, 'system_approve')
        add_log('verify', f"Manuel rozet: @{u.username} → {BADGES[badge]['label']}")
        db.session.commit()
        return jsonify({'message': f'@{u.username} → {BADGES[badge]["label"]} rozeti verildi!'})
    else:
        u.is_verified = False; u.badge_key = None; u.verification_status = 'none'
        add_log('verify', f"Rozet kaldırıldı: @{u.username}")
        db.session.commit()
        return jsonify({'message': f'@{u.username} rozeti kaldırıldı.'})

# ─────────────────────────── RUN ───────────────────────────@app.route('/api/like/<int:vid>', methods=['POST'])
@login_required
def like_video(vid):
    video = Video.query.get_or_404(vid)
    if current_user in video.liked_by:
        video.liked_by.remove(current_user); action = 'unliked'
    else:
        video.liked_by.append(current_user)
        push_notif(video.user_id, current_user.id, 'like', vid)
        action = 'liked'
    db.session.commit()
    return jsonify({'action': action, 'count': len(video.liked_by)})

@app.route('/api/view/<int:vid>', methods=['POST'])
def view_video(vid):
    v = Video.query.get(vid)
    if v: v.views += 1; db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/bookmark/<int:vid>', methods=['POST'])
@login_required
def bookmark_video(vid):
    video = Video.query.get_or_404(vid)
    if video in current_user.bookmarked_videos:
        current_user.bookmarked_videos.remove(video); action = 'removed'
    else:
        current_user.bookmarked_videos.append(video); action = 'added'
    db.session.commit()
    return jsonify({'action': action})

@app.route('/api/report/<int:vid>', methods=['POST'])
@login_required
def report_video(vid):
    if not Report.query.filter_by(reporter_id=current_user.id, video_id=vid).first():
        data   = request.get_json() or {}
        reason = data.get('reason', 'Belirtilmedi')[:200]
        db.session.add(Report(reporter_id=current_user.id, video_id=vid, reason=reason))
        db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/follow/<int:uid>', methods=['POST'])
@login_required
def follow_user(uid):
    user = User.query.get_or_404(uid)
    if user.id == current_user.id: return jsonify({'error': 'Kendini takip edemezsin'}), 400
    if current_user.is_following(user):
        current_user.unfollow(user); action = 'unfollowed'
    else:
        current_user.follow(user)
        push_notif(user.id, current_user.id, 'follow')
        action = 'followed'
    db.session.commit()
    return jsonify({'action': action})

@app.route('/api/comment/<int:vid>', methods=['GET', 'POST'])
def comment_video(vid):
    if request.method == 'POST':
        if not current_user.is_authenticated:
            return jsonify({'error': 'Giriş gerekli'}), 401
        data = request.get_json() or {}
        text = data.get('text', '').strip()
        if not text: return jsonify({'error': 'Boş yorum!'}), 400
        if contains_bad_words(text): return jsonify({'error': 'Uygunsuz içerik!'}), 400
        pid = data.get('parent_id')
        c   = Comment(text=text, user_id=current_user.id, video_id=vid, parent_id=pid)
        db.session.add(c)
        video = Video.query.get(vid)
        if video:
            if pid:
                parent = Comment.query.get(pid)
                if parent: push_notif(parent.user_id, current_user.id, 'comment', vid)
            else:
                push_notif(video.user_id, current_user.id, 'comment', vid)
        db.session.commit()
        return jsonify({'status': 'success'})

    # GET
    video    = Video.query.get_or_404(vid)
    comments = Comment.query.filter_by(video_id=vid, parent_id=None
               ).order_by(Comment.created_at.desc()).all()

    def serialize(c):
        user_liked = current_user.is_authenticated and current_user in c.liked_by
        badge_svg  = BADGES[c.user.badge_key]['svg'] if c.user.badge_key and c.user.badge_key in BADGES else ''
        return {
            'id': c.id, 'username': c.user.username, 'text': c.text,
            'avatar': c.user.avatar or '',
            'is_video_owner': video.user_id == c.user_id,
            'liked_by_creator': c.is_liked_by_creator,
            'like_count': len(c.liked_by), 'user_liked': user_liked,
            'is_verified': c.user.is_verified, 'badge': badge_svg,
            'replies': [serialize(r) for r in c.replies.order_by(Comment.created_at.asc()).all()]
        }
    return jsonify([serialize(c) for c in comments])

@app.route('/api/like_comment/<int:cid>', methods=['POST'])
@login_required
def like_comment(cid):
    c = Comment.query.get_or_404(cid)
    if c.video and current_user.id == c.video.user_id:
        c.is_liked_by_creator = not c.is_liked_by_creator
    if current_user in c.liked_by:
        c.liked_by.remove(current_user); action = 'unliked'
    else:
        c.liked_by.append(current_user); action = 'liked'
    db.session.commit()
    return jsonify({'action': action, 'likes': len(c.liked_by), 'creator_liked': c.is_liked_by_creator})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # Render için Port ayarı
    port = int(os.environ.get('PORT', 5000))
    
    # Canlı ortamda debug=False olmalı
    socketio.run(app, host='0.0.0.0', port=port)
