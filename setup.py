import os

# --- APP.PY ---
app_py_code = """import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, login_user, LoginManager, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.sql import func, or_, and_
from sqlalchemy import case, event
from sqlalchemy.engine import Engine
from flask_socketio import SocketIO, emit, join_room
import uuid
import datetime
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'vetrico-v23-fix-complete'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vertico.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['AVATAR_FOLDER'] = 'static/avatars'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm'}
ALLOWED_IMG_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
BAD_WORDS = ['amk', 'aq', 'oç', 'piç', 'sik', 'yarrak', 'amcık', 'göt', 'kaşar', 'orospu', 'salak', 'gerizekalı', 'aptal', 'mal', 'ananı', 'sikerim', 'şerefsiz']

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

def contains_bad_words(text):
    if not text: return False
    text = text.replace('İ', 'i').replace('I', 'ı').lower()
    for word in BAD_WORDS:
        if re.search(r'\\b' + re.escape(word) + r'\\b', text): return True
        if word in ['amk', 'aq', 'oç', 'sik', 'piç'] and word in text: return True
    return False

for folder in [app.config['UPLOAD_FOLDER'], app.config['AVATAR_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)
online_users = {}

# --- MODELLER ---
followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)
likes = db.Table('likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('video_id', db.Integer, db.ForeignKey('video.id', ondelete="CASCADE"))
)
bookmarks = db.Table('bookmarks',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('video_id', db.Integer, db.ForeignKey('video.id', ondelete="CASCADE"))
)
comment_likes = db.Table('comment_likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('comment_id', db.Integer, db.ForeignKey('comment.id', ondelete="CASCADE"))
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    bio = db.Column(db.String(250), default="Vetrico dünyasına hoş geldin.")
    avatar = db.Column(db.String(300), nullable=True)
    coins = db.Column(db.Integer, default=50)
    last_bonus_date = db.Column(db.Date, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    verification_status = db.Column(db.String(20), default='none')
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    followed = db.relationship('User', secondary=followers, primaryjoin=(followers.c.follower_id == id), secondaryjoin=(followers.c.followed_id == id), backref=db.backref('followers', lazy='dynamic'), lazy='dynamic')
    bookmarked_videos = db.relationship('Video', secondary=bookmarks, backref=db.backref('bookmarked_by', lazy='dynamic'))
    notifications = db.relationship('Notification', backref='recipient', foreign_keys='Notification.recipient_id', lazy='dynamic', cascade="all, delete-orphan")
    def is_following(self, user): return self.followed.filter(followers.c.followed_id == user.id).count() > 0
    def follow(self, user): 
        if not self.is_following(user): self.followed.append(user)
    def unfollow(self, user): 
        if self.is_following(user): self.followed.remove(user)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(300), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    caption = db.Column(db.String(500))
    category = db.Column(db.String(50), default='Genel')
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    user = db.relationship('User', backref='videos')
    liked_by = db.relationship('User', secondary=likes, backref=db.backref('liked_videos', lazy='dynamic'))
    comments = db.relationship('Comment', backref='video', cascade="all, delete-orphan", lazy='dynamic')
    reports = db.relationship('Report', backref='video', cascade="all, delete-orphan", lazy='dynamic')
    reactions = db.relationship('Reaction', backref='video', cascade="all, delete-orphan", lazy='dynamic')

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    video_id = db.Column(db.Integer, db.ForeignKey('video.id', ondelete="CASCADE"))
    emoji = db.Column(db.String(10))
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(500), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    video_id = db.Column(db.Integer, db.ForeignKey('video.id', ondelete="CASCADE"))
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id', ondelete="CASCADE"), nullable=True)
    is_liked_by_creator = db.Column(db.Boolean, default=False)
    user = db.relationship('User')
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), cascade="all, delete-orphan", lazy='dynamic')
    liked_by = db.relationship('User', secondary=comment_likes, backref=db.backref('liked_comments', lazy='dynamic'))

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    type = db.Column(db.String(20))
    post_id = db.Column(db.Integer, nullable=True)
    amount = db.Column(db.Integer, nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime(timezone=True), server_default=func.now())
    sender = db.relationship('User', foreign_keys=[sender_id])

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    body = db.Column(db.String(1000))
    timestamp = db.Column(db.DateTime(timezone=True), server_default=func.now())
    is_read = db.Column(db.Boolean, default=False)

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    video_id = db.Column(db.Integer, db.ForeignKey('video.id', ondelete="CASCADE"))
    reason = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime(timezone=True), server_default=func.now())
    reporter = db.relationship('User')

def allowed_file(filename): return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def allowed_img(filename): return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMG_EXTENSIONS
@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))
@app.context_processor
def inject_globals():
    notif_count = 0
    if current_user.is_authenticated:
        notif_count = Notification.query.filter_by(recipient_id=current_user.id, is_read=False).count()
    return {'unread_notifications': notif_count}
def create_notification(recipient, type, post_id=None, amount=None):
    if recipient.id == current_user.id: return 
    notif = Notification(recipient_id=recipient.id, sender_id=current_user.id, type=type, post_id=post_id, amount=amount)
    db.session.add(notif); db.session.commit()
def case_user_id(m): return case((m.sender_id == current_user.id, m.recipient_id), else_=m.sender_id)

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        join_room(f"user_{current_user.id}")
        if current_user.id not in online_users: online_users[current_user.id] = set()
        online_users[current_user.id].add(request.sid)
        emit('user_status', {'user_id': current_user.id, 'status': 'online'}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated and current_user.id in online_users:
        online_users[current_user.id].discard(request.sid)
        if not online_users[current_user.id]: del online_users[current_user.id]; emit('user_status', {'user_id': current_user.id, 'status': 'offline'}, broadcast=True)

@socketio.on('send_message')
def handle_send_message(data):
    if contains_bad_words(data['body']): return
    msg = Message(sender_id=current_user.id, recipient_id=data['recipient_id'], body=data['body'])
    db.session.add(msg); db.session.commit()
    emit('receive_message', {'sender_id': current_user.id, 'body': data['body'], 'timestamp': datetime.datetime.now().strftime('%H:%M')}, room=f"user_{data['recipient_id']}")
    emit('message_sent', {'body': data['body'], 'timestamp': datetime.datetime.now().strftime('%H:%M')})

@socketio.on('typing')
def handle_typing(data): emit('display_typing', {'sender_id': current_user.id}, room=f"user_{data['recipient_id']}")
@socketio.on('stop_typing')
def handle_stop_typing(data): emit('hide_typing', {'sender_id': current_user.id}, room=f"user_{data['recipient_id']}")
@socketio.on('send_reaction')
def handle_reaction(data): emit('animate_reaction', {'video_id': data['video_id'], 'emoji': data['emoji']}, broadcast=True)

@app.route('/')
def index():
    bonus_msg = None
    if current_user.is_authenticated:
        today = datetime.date.today()
        if current_user.last_bonus_date != today:
            current_user.coins += 10; current_user.last_bonus_date = today; db.session.commit(); bonus_msg = "🎉 Günlük Giriş Ödülü: +10 Coin!"
    videos = Video.query.order_by(func.random()).limit(30).all()
    stories = []
    if current_user.is_authenticated:
        followed_ids = [u.id for u in current_user.followed]
        for fid in followed_ids:
            vid = Video.query.filter_by(user_id=fid).order_by(Video.created_at.desc()).first()
            if vid: stories.append(vid)
    if bonus_msg: flash(bonus_msg)
    return render_template('home.html', videos=videos, stories=stories)

@app.route('/watch/<int:video_id>')
def watch(video_id):
    target = Video.query.get_or_404(video_id)
    others = Video.query.filter(Video.id != video_id).order_by(func.random()).limit(15).all()
    return render_template('feed.html', videos=[target] + others)

@app.route('/hashtag/<tag>')
def hashtag_view(tag):
    tag_clean = tag.replace('#', '')
    videos = Video.query.filter(Video.caption.ilike(f'%#{tag_clean}%')).all()
    return render_template('search.html', videos=videos, query=f"#{tag_clean}", users=[])

@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    file = request.files.get('avatar')
    if file and allowed_img(file.filename):
        filename = "avatar_" + str(uuid.uuid4()) + ".jpg"
        file.save(os.path.join(app.config['AVATAR_FOLDER'], filename))
        current_user.avatar = filename; db.session.commit(); flash("Profil resmi güncellendi!")
    return redirect(url_for('profile', username=current_user.username))

@app.route('/api/bookmark/<int:video_id>', methods=['POST'])
@login_required
def bookmark_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video in current_user.bookmarked_videos: current_user.bookmarked_videos.remove(video); action='removed'
    else: current_user.bookmarked_videos.append(video); action='added'
    db.session.commit(); return jsonify({'action': action})

@app.route('/api/gift/<int:video_id>', methods=['POST'])
@login_required
def send_gift(video_id):
    amount = 10; video = Video.query.get_or_404(video_id)
    if current_user.coins < amount: return jsonify({'error': 'Yetersiz bakiye'}), 400
    if video.user_id == current_user.id: return jsonify({'error': 'Kendine hediye atamazsın'}), 400
    current_user.coins -= amount; video.user.coins += amount
    create_notification(video.user, 'gift', video.id, amount); db.session.commit()
    return jsonify({'success': True, 'new_balance': current_user.coins})

@app.route('/api/report/<int:video_id>', methods=['POST'])
@login_required
def report_video(video_id):
    video = Video.query.get_or_404(video_id)
    if Report.query.filter_by(reporter_id=current_user.id, video_id=video_id).first(): return jsonify({'message': 'Zaten raporladınız.'})
    report = Report(reporter_id=current_user.id, video_id=video.id, reason=request.json.get('reason', 'Uygunsuz'))
    db.session.add(report); db.session.commit(); return jsonify({'message': 'Rapor alındı.'})

@app.route('/api/view/<int:video_id>', methods=['POST'])
def view_video(video_id):
    video = Video.query.get_or_404(video_id); video.views += 1; db.session.commit()
    return jsonify({'views': video.views})

@app.route('/apply_verification', methods=['POST'])
@login_required
def apply_verification():
    current_user.verification_status = 'pending'; db.session.commit(); return redirect(url_for('profile', username=current_user.username))

@app.route('/admin/approve_verification/<int:user_id>')
@login_required
def approve_verification(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id); user.is_verified = True; user.verification_status = 'approved'; db.session.commit(); create_notification(user, 'system_approve')
    return redirect(url_for('admin_panel'))

@app.route('/admin/reject_verification/<int:user_id>')
@login_required
def reject_verification(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id); user.is_verified = False; user.verification_status = 'rejected'; db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/dismiss_report/<int:report_id>')
@login_required
def dismiss_report(report_id):
    if not current_user.is_admin: abort(403)
    Report.query.filter_by(id=report_id).delete(); db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/search')
def search():
    query = request.args.get('q'); users = []; videos = []
    if query:
        users = User.query.filter(User.username.ilike(f'%{query}%')).all()
        videos = Video.query.filter(Video.caption.ilike(f'%{query}%')).all()
    return render_template('search.html', users=users, videos=videos, query=query)

@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(recipient_id=current_user.id).order_by(Notification.timestamp.desc()).all()
    for n in notifs: n.is_read = True
    db.session.commit(); return render_template('notifications.html', notifications=notifs)

@app.route('/messages')
@login_required
def messages():
    subq = db.session.query(func.max(Message.timestamp).label('max_time'), case_user_id(Message).label('other_user_id')).group_by('other_user_id').subquery()
    all_msgs = Message.query.filter(or_(Message.sender_id==current_user.id, Message.recipient_id==current_user.id)).order_by(Message.timestamp.desc()).all()
    conversations = {}
    for m in all_msgs:
        other_id = m.recipient_id if m.sender_id == current_user.id else m.sender_id
        if other_id not in conversations:
            other_user = User.query.get(other_id)
            if other_user: conversations[other_id] = {'user': other_user, 'last_msg': m, 'is_online': other_id in online_users}
    return render_template('chat_list.html', conversations=conversations.values())

@app.route('/messages/<int:user_id>')
@login_required
def chat_detail(user_id):
    other_user = User.query.get_or_404(user_id); is_online = user_id in online_users
    msgs = Message.query.filter(or_(and_(Message.sender_id==current_user.id, Message.recipient_id==user_id), and_(Message.sender_id==user_id, Message.recipient_id==current_user.id))).order_by(Message.timestamp.asc()).all()
    for m in msgs:
        if m.recipient_id == current_user.id: m.is_read = True
    db.session.commit(); return render_template('chat_detail.html', other_user=other_user, messages=msgs, is_online=is_online)

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin: abort(403)
    stats = {'users': User.query.count(), 'videos': Video.query.count(), 'likes': db.session.query(likes).count(), 'reports': Report.query.count()}
    pending_verifications = User.query.filter_by(verification_status='pending').all()
    reports = Report.query.order_by(Report.timestamp.desc()).all()
    users = User.query.order_by(User.id.desc()).limit(20).all()
    videos = Video.query.order_by(Video.id.desc()).limit(20).all()
    return render_template('admin.html', stats=stats, users=users, videos=videos, pending_verifications=pending_verifications, reports=reports)

@app.route('/admin/delete_video/<int:video_id>')
@login_required
def admin_delete_video(video_id):
    if not current_user.is_admin: abort(403)
    Video.query.filter_by(id=video_id).delete(); db.session.commit(); flash('Video silindi'); return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<int:user_id>')
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin: abort(403)
    User.query.filter_by(id=user_id).delete(); db.session.commit(); flash('Kullanıcı banlandı'); return redirect(url_for('admin_panel'))

@app.route('/api/like/<int:video_id>', methods=['POST'])
@login_required
def like_video(video_id):
    video = Video.query.get_or_404(video_id)
    if current_user in video.liked_by: video.liked_by.remove(current_user); action = 'unliked'
    else: video.liked_by.append(current_user); create_notification(video.user, 'like', video.id); current_user.coins += 1; action = 'liked'
    db.session.commit(); return jsonify({'action': action, 'count': len(video.liked_by)})

@app.route('/api/comment/<int:video_id>', methods=['GET', 'POST'])
def comment_video(video_id):
    if request.method == 'POST':
        if not current_user.is_authenticated: return jsonify({'error': 'Login required'}), 401
        data = request.get_json()
        if contains_bad_words(data.get('text')): return jsonify({'error': 'Uygunsuz içerik!'}), 400
        new_comment = Comment(text=data.get('text'), user_id=current_user.id, video_id=video_id, parent_id=data.get('parent_id'))
        db.session.add(new_comment); video = Video.query.get(video_id)
        if data.get('parent_id'): create_notification(Comment.query.get(data.get('parent_id')).user, 'comment', video.id)
        else: create_notification(video.user, 'comment', video.id)
        current_user.coins += 2; db.session.commit()
        return jsonify({'status': 'success'})
    comments = Comment.query.filter_by(video_id=video_id, parent_id=None).order_by(Comment.created_at.desc()).all()
    def serialize(c):
        is_liked = False
        if current_user.is_authenticated: is_liked = current_user in c.liked_by
        return {'id': c.id, 'username': c.user.username, 'text': c.text, 'avatar': c.user.avatar, 'is_video_owner': c.video.user_id == c.user_id, 'liked_by_creator': c.is_liked_by_creator, 'like_count': len(c.liked_by), 'user_liked': is_liked, 'replies': [serialize(r) for r in c.replies]}
    return jsonify([serialize(c) for c in comments])

@app.route('/api/like_comment/<int:comment_id>', methods=['POST'])
@login_required
def like_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id); video = comment.video
    if current_user.id == video.user_id: comment.is_liked_by_creator = not comment.is_liked_by_creator
    if current_user in comment.liked_by: comment.liked_by.remove(current_user); action = 'unliked'
    else: comment.liked_by.append(current_user); action = 'liked'
    db.session.commit(); return jsonify({'action': action, 'likes': len(comment.liked_by), 'creator_liked': comment.is_liked_by_creator})

@app.route('/api/follow/<int:user_id>', methods=['POST'])
@login_required
def follow_user(user_id):
    user = User.query.get_or_404(user_id)
    if current_user.is_following(user): current_user.unfollow(user); action = 'unfollowed'
    else: current_user.follow(user); create_notification(user, 'follow'); action = 'followed'
    db.session.commit(); return jsonify({'action': action})

@app.route('/profile/<username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    bookmarked = user.bookmarked_videos if current_user.is_authenticated and current_user.id == user.id else []
    user_videos = Video.query.filter_by(user_id=user.id).order_by(Video.id.desc()).all()
    is_following = False
    if current_user.is_authenticated: is_following = current_user.is_following(user)
    return render_template('profile.html', user=user, videos=user_videos, bookmarked=bookmarked, is_following=is_following)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        file = request.files.get('file'); caption = request.form.get('caption')
        if contains_bad_words(caption): flash("Uygunsuz içerik!"); return redirect(url_for('upload'))
        if file and allowed_file(file.filename):
            filename = str(uuid.uuid4()) + "_" + secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            db.session.add(Video(filename=filename, user_id=current_user.id, caption=caption, category=request.form.get('category')))
            db.session.commit(); return redirect(url_for('profile', username=current_user.username))
    return render_template('upload.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']): login_user(user); return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        if contains_bad_words(username): flash("Uygunsuz kullanıcı adı!"); return redirect(url_for('register'))
        if not User.query.filter_by(username=username).first():
            is_admin = (username.lower() == 'admin')
            new_user = User(username=username, password=generate_password_hash(request.form['password'], method='pbkdf2:sha256'), is_admin=is_admin)
            db.session.add(new_user); db.session.commit(); login_user(new_user); return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('index'))

@app.route('/video/edit/<int:video_id>', methods=['GET', 'POST'])
@login_required
def edit_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.user_id != current_user.id: abort(403)
    if request.method == 'POST':
        caption = request.form.get('caption')
        if contains_bad_words(caption): flash("Uygunsuz içerik!"); return redirect(url_for('edit_video', video_id=video.id))
        video.caption = caption; db.session.commit(); return redirect(url_for('profile', username=current_user.username))
    return render_template('edit_video.html', video=video)

@app.route('/video/delete/<int:video_id>')
@login_required
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.user_id != current_user.id: abort(403)
    try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], video.filename))
    except: pass
    db.session.delete(video); db.session.commit(); return redirect(url_for('profile', username=current_user.username))

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)
"""

# --- LAYOUT.HTML (RESPONSIVE NOTIFICATION FIX & AUTO-DISMISS) ---
layout_html_code = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, interactive-widget=resizes-content">
    <title>Vetrico</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css"/>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        ::-webkit-scrollbar { width: 0px; background: transparent; }
        * { -webkit-tap-highlight-color: transparent; }
        body, html { margin: 0; padding: 0; height: 100%; width: 100%; background-color: #000; color: #fff; font-family: 'Outfit', sans-serif; overflow: hidden; }
        .full-dvh { height: 100dvh; }
        .glass { background: rgba(20, 20, 20, 0.6); backdrop-filter: blur(20px); border-top: 1px solid rgba(255, 255, 255, 0.1); }
        .glass-pc { background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(24px); border: 1px solid rgba(255, 255, 255, 0.08); }
        .shorts-wrapper { height: 100dvh; width: 100%; overflow-y: scroll; scroll-snap-type: y mandatory; scroll-behavior: smooth; }
        .video-section { height: 100dvh; width: 100%; scroll-snap-align: start; scroll-snap-stop: always; }
        @keyframes slideInUpFade { from { opacity: 0; transform: translateY(15px); } to { opacity: 1; transform: translateY(0); } }
        .page-enter { animation: slideInUpFade 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
        .z-modal { z-index: 9999 !important; }
        #mobile-nav { transition: transform 0.3s ease-in-out; }
        #mobile-nav.hidden-nav { transform: translateY(100%); }
    </style>
</head>
<body class="bg-black">
    <div class="flex h-full w-full full-dvh">
        <aside class="hidden md:flex flex-col w-20 lg:w-64 h-[96%] my-auto ml-4 glass-pc rounded-3xl p-6 justify-between z-50">
            <div>
                <a href="/" class="flex items-center gap-3 mb-10 px-2 group"><div class="w-10 h-10 bg-gradient-to-tr from-red-600 to-purple-600 rounded-xl flex items-center justify-center text-xl font-bold group-hover:rotate-12 transition">V</div><span class="text-3xl font-bold hidden lg:block tracking-tighter">Vetrico</span></a>
                <nav class="flex flex-col gap-3">
                    <a href="/" class="flex items-center gap-4 px-4 py-3 rounded-2xl hover:bg-white/10 transition text-lg font-medium"><span class="text-2xl">🏠</span> <span class="hidden lg:block">Ana Sayfa</span></a>
                    <a href="/search" class="flex items-center gap-4 px-4 py-3 rounded-2xl hover:bg-white/10 transition text-lg font-medium"><span class="text-2xl">⚡</span> <span class="hidden lg:block">Keşfet</span></a>
                    {% if current_user.is_authenticated %}
                    <a href="/notifications" class="flex items-center gap-4 px-4 py-3 rounded-2xl hover:bg-white/10 transition text-lg font-medium relative"><span class="text-2xl">🔔</span> <span class="hidden lg:block">Bildirimler</span>{% if unread_notifications > 0 %}<span class="absolute top-3 left-8 w-2 h-2 bg-red-500 rounded-full animate-ping"></span>{% endif %}</a>
                    <a href="/messages" class="flex items-center gap-4 px-4 py-3 rounded-2xl hover:bg-white/10 transition text-lg font-medium"><span class="text-2xl">💬</span> <span class="hidden lg:block">Mesajlar</span></a>
                    <a href="{{ url_for('profile', username=current_user.username) }}" class="flex items-center gap-4 px-4 py-3 rounded-2xl hover:bg-white/10 transition text-lg font-medium"><span class="text-2xl">👤</span> <span class="hidden lg:block">Profil</span></a>
                    <a href="/upload" class="flex items-center gap-4 px-4 py-3 rounded-2xl hover:bg-white/10 transition text-lg font-medium text-red-400"><span class="text-2xl">🔥</span> <span class="hidden lg:block">Oluştur</span></a>
                    {% if current_user.is_admin %}<a href="/admin" class="flex items-center gap-4 px-4 py-3 rounded-2xl hover:bg-white/10 transition text-lg font-medium text-blue-400"><span class="text-2xl">🛡️</span> <span class="hidden lg:block">Admin</span></a>{% endif %}
                    {% else %}
                    <a href="/login" class="flex items-center gap-4 px-4 py-3 rounded-2xl bg-white/10 hover:bg-white/20 transition text-lg font-bold"><span class="text-2xl">🔑</span> <span class="hidden lg:block">Giriş</span></a>
                    {% endif %}
                </nav>
            </div>
        </aside>
        <main class="flex-1 relative h-full w-full page-enter md:p-0"> {% block content %}{% endblock %} </main>
        <nav id="mobile-nav" class="md:hidden fixed bottom-0 left-0 w-full h-16 glass flex justify-around items-center px-2 z-50 shadow-[0_-5px_20px_rgba(0,0,0,0.5)]">
            <a href="/" class="nav-item flex flex-col items-center gap-1 text-gray-400 hover:text-white transition p-2"><svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" /></svg></a>
            <a href="/search" class="nav-item flex flex-col items-center gap-1 text-gray-400 hover:text-white transition p-2"><svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg></a>
            <a href="/upload" class="relative -top-5"><div class="w-14 h-14 rounded-full bg-gradient-to-tr from-red-600 to-pink-600 flex items-center justify-center text-3xl text-white shadow-lg border-4 border-black animate-pulse">+</div></a>
            <a href="/messages" class="nav-item flex flex-col items-center gap-1 text-gray-400 hover:text-white transition p-2"><svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" /></svg></a>
            <a href="{{ url_for('profile', username=current_user.username) if current_user.is_authenticated else '/login' }}" class="nav-item flex flex-col items-center gap-1 text-gray-400 hover:text-white transition p-2"><svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg></a>
        </nav>
    </div>
    {% with messages = get_flashed_messages() %} 
        {% if messages %} 
        <div id="flash-message" class="fixed top-24 left-1/2 -translate-x-1/2 z-[200] w-[90%] max-w-sm pointer-events-none transition-all duration-500 ease-out transform translate-y-0 opacity-100">
            <div class="bg-gradient-to-r from-green-500 to-emerald-600 text-white p-4 rounded-2xl shadow-2xl font-bold flex items-center justify-center gap-3 text-center border border-white/20 backdrop-blur-md">
                <span class="text-xl">🎁</span>
                <span class="text-sm md:text-base leading-tight break-words">{{ messages[0] }}</span>
            </div>
        </div>
        <script>
            document.addEventListener('DOMContentLoaded', () => {
                const flash = document.getElementById('flash-message');
                if (flash) {
                    setTimeout(() => {
                        flash.style.transform = 'translate(-50%, -20px)';
                        flash.style.opacity = '0';
                        setTimeout(() => flash.remove(), 500);
                    }, 3000);
                }
            });
        </script>
        {% endif %} 
    {% endwith %}
</body>
</html>
"""

# --- HOME.HTML ---
home_html_code = """{% extends "layout.html" %} {% block content %} <div class="h-full overflow-y-auto pb-24 md:p-0"> <div class="flex justify-between items-center p-4 sticky top-0 bg-black/90 backdrop-blur-md z-30 border-b border-white/5"> <a href="/" class="flex items-center gap-2"> <div class="w-8 h-8 bg-gradient-to-tr from-red-600 to-purple-600 rounded-lg flex items-center justify-center font-bold">V</div> <span class="text-xl font-bold tracking-tighter">Vetrico</span> </a> <a href="/notifications" class="text-2xl hover:text-red-500 relative"> 🔔 {% if unread_notifications > 0 %}<span class="absolute top-0 right-0 w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>{% endif %} </a> </div> <div class="pl-4 py-4 mb-4 border-b border-white/5"> <div class="flex gap-4 overflow-x-auto no-scrollbar pr-4"> <a href="/upload" class="flex flex-col items-center gap-2 min-w-[70px]"> <div class="w-16 h-16 rounded-full border-2 border-dashed border-gray-600 flex items-center justify-center bg-gray-900 relative"><span class="text-2xl text-gray-400">+</span></div> <span class="text-xs text-gray-400">Sen</span> </a> {% for story in stories %} <a href="/watch/{{ story.id }}" class="flex flex-col items-center gap-2 min-w-[70px]"> <div class="w-16 h-16 rounded-full p-[2px] bg-gradient-to-tr from-yellow-400 via-red-500 to-purple-600"> <div class="w-full h-full rounded-full overflow-hidden border-2 border-black"> {% if story.user.avatar %}<img src="/static/avatars/{{ story.user.avatar }}" class="w-full h-full object-cover">{% else %}<div class="w-full h-full bg-gray-800 flex items-center justify-center font-bold">{{ story.user.username[0]|upper }}</div>{% endif %} </div> </div> <span class="text-xs text-gray-300 w-16 truncate text-center">{{ story.user.username }}</span> </a> {% endfor %} </div> </div> <div class="px-4"> <h2 class="text-lg font-bold text-white mb-4 flex items-center gap-2">Keşfet <span class="text-xs bg-red-600 text-white px-2 py-0.5 rounded-full">LIVE</span></h2> <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3"> {% for video in videos %} <a href="/watch/{{ video.id }}" class="aspect-[9/16] bg-gray-900 rounded-2xl overflow-hidden relative group cursor-pointer border border-white/5 hover:border-white/20 transition shadow-lg"> <video src="{{ url_for('static', filename='uploads/' + video.filename) }}" class="w-full h-full object-cover opacity-90 group-hover:opacity-100 transition duration-500"></video> <div class="absolute bottom-0 left-0 w-full p-2 bg-gradient-to-t from-black/90 to-transparent"> <div class="text-xs font-bold text-white truncate">@{{ video.user.username }}</div> <div class="text-[10px] text-gray-400 mt-1 flex justify-between"><span>👁️ {{ video.views }}</span></div> </div> </a> {% endfor %} </div> </div> </div> {% endblock %} """

# --- FEED.HTML ---
feed_html_code = """{% extends "layout.html" %} {% block content %} <div id="reaction-layer" class="fixed inset-0 pointer-events-none z-[100] overflow-hidden"></div> <div class="shorts-wrapper flex flex-col items-center w-full"> {% for video in videos %} <div class="video-section w-full h-full flex justify-center items-center snap-start relative bg-black" data-id="{{ video.id }}"> <div class="relative w-full h-full md:w-[450px] md:h-[calc(100dvh-20px)] md:rounded-[2rem] overflow-hidden bg-black shadow-2xl group flex items-center justify-center"> <div class="absolute inset-0 z-0"><video src="{{ url_for('static', filename='uploads/' + video.filename) }}" class="w-full h-full object-cover blur-2xl opacity-50"></video></div> <video src="{{ url_for('static', filename='uploads/' + video.filename) }}" class="relative z-10 max-w-full max-h-full object-contain cursor-pointer shadow-xl" loop playsinline onclick="togglePlay(this)"></video> <div class="absolute bottom-0 left-0 w-full p-5 pb-24 md:pb-8 z-20 bg-gradient-to-t from-black/90 via-black/50 to-transparent"> <div class="flex items-center gap-3 mb-2"> <a href="{{ url_for('profile', username=video.user.username) }}" class="font-bold flex items-center gap-2 group/user cursor-pointer"> {% if video.user.avatar %}<img src="/static/avatars/{{ video.user.avatar }}" class="w-10 h-10 rounded-full object-cover border-2 border-white/50">{% else %}<div class="w-10 h-10 bg-gray-700 rounded-full flex items-center justify-center font-bold border-2 border-white/20">{{ video.user.username[0] | upper }}</div>{% endif %} <span class="text-white text-shadow hover:underline text-sm">@{{ video.user.username }}</span> {% if video.user.is_verified %}<span class="verified-badge">✓</span>{% endif %} </a> {% if current_user.is_authenticated and current_user.id != video.user_id and not current_user.is_following(video.user) %} <button id="follow-btn-{{ video.user.id }}" onclick="followUser({{ video.user.id }})" class="bg-red-600 text-white text-xs px-3 py-1 rounded-full font-bold shadow-lg">Takip Et</button> {% endif %} </div> <p class="text-gray-100 text-sm pl-1 leading-relaxed caption-text mb-2 drop-shadow-md">{{ video.caption }}</p> </div> <div class="absolute bottom-24 right-2 md:bottom-24 md:right-4 flex flex-col gap-4 items-center z-30"> <div class="flex flex-col gap-2 bg-black/40 p-2 rounded-full backdrop-blur-md mb-2"> <button onclick="sendReaction('🔥', {{ video.id }})" class="text-2xl hover:scale-125 transition">🔥</button> <button onclick="sendReaction('😂', {{ video.id }})" class="text-2xl hover:scale-125 transition">😂</button> <button onclick="sendReaction('❤️', {{ video.id }})" class="text-2xl hover:scale-125 transition">❤️</button> </div> <div class="flex flex-col items-center"><button onclick="likeVideo({{ video.id }})" class="w-10 h-10 transition active:scale-75"><span id="like-icon-{{ video.id }}" class="text-3xl drop-shadow-lg {{ 'text-red-500' if current_user in video.liked_by else 'text-white' }}">♥</span></button><span id="like-count-{{ video.id }}" class="text-xs font-bold drop-shadow-md mt-1">{{ video.liked_by|length }}</span></div> <div class="flex flex-col items-center"><button onclick="openComments({{ video.id }})" class="w-10 h-10 transition active:scale-75 text-3xl text-white drop-shadow-lg">💬</button><span class="text-xs font-bold drop-shadow-md mt-1">{{ video.comments.count() }}</span></div> <button onclick="bookmarkVideo({{ video.id }})" class="w-10 h-10 transition active:scale-75 text-3xl drop-shadow-lg"><span id="bookmark-icon-{{ video.id }}" class="{{ 'text-yellow-400' if video in current_user.bookmarked_videos else 'text-white' }}">🔖</span></button> <button onclick="reportVideo({{ video.id }})" class="w-8 h-8 bg-black/40 rounded-full flex items-center justify-center text-xs mt-2 text-gray-400 border border-white/10 hover:bg-red-500/50">🚩</button> </div> </div> </div> {% endfor %} </div> <div id="commentModal" class="fixed inset-0 z-modal hidden"> <div class="absolute inset-0 bg-black/80 backdrop-blur-sm transition-opacity" onclick="closeComments()"></div> <div class="absolute bottom-0 w-full md:w-[450px] md:left-1/2 md:-translate-x-1/2 h-[80vh] glass-dark rounded-t-[2rem] flex flex-col transition-transform duration-500 transform translate-y-full border-t border-white/10" id="commentSheet"> <div class="w-12 h-1 bg-gray-600 rounded-full mx-auto mt-4 mb-2"></div> <div class="p-4 border-b border-white/5"><h3 class="font-bold text-center text-lg">Yorumlar</h3></div> <div id="commentsList" class="flex-1 overflow-y-auto p-4 space-y-6"></div> <div class="p-4 bg-black/80 backdrop-blur-md pb-8 md:pb-4 border-t border-white/10"> <div id="replyingTo" class="text-xs text-gray-400 mb-2 hidden">Yanıt veriliyor... <button onclick="cancelReply()" class="text-white ml-2">İptal</button></div> <div class="flex gap-2 items-center"> <input type="text" id="commentInput" placeholder="Yorum yap..." class="flex-1 bg-white/10 rounded-full px-5 py-3 outline-none focus:ring-1 focus:ring-red-500 transition text-sm text-white"> <button onclick="postComment()" class="w-10 h-10 bg-red-600 rounded-full flex items-center justify-center hover:scale-110 transition text-white">➤</button> </div> </div> </div> </div> <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script> <script> const socket = io(); let currentVideoId = null; let viewedVideos = new Set(); let replyingToId = null; socket.on('animate_reaction', function(data) { animateEmoji(data.emoji); }); function sendReaction(emoji, vidId) { socket.emit('send_reaction', { emoji: emoji, video_id: vidId }); animateEmoji(emoji); } function animateEmoji(emoji) { const layer = document.getElementById('reaction-layer'); const el = document.createElement('div'); el.innerText = emoji; el.style.position = 'absolute'; el.style.bottom = '100px'; el.style.right = (20 + Math.random() * 50) + 'px'; el.style.fontSize = (30 + Math.random() * 20) + 'px'; el.style.transition = 'all 2s ease-out'; el.style.opacity = '1'; el.style.zIndex = '9999'; layer.appendChild(el); requestAnimationFrame(() => { el.style.transform = `translateY(-${400 + Math.random() * 200}px) rotate(${Math.random() * 90 - 45}deg)`; el.style.opacity = '0'; }); setTimeout(() => { el.remove(); }, 2000); } function togglePlay(v) { v.paused ? v.play() : v.pause(); } const observer = new IntersectionObserver((entries) => { entries.forEach(entry => { const vid = entry.target.querySelector('video.relative'); const vidId = entry.target.getAttribute('data-id'); if (entry.isIntersecting) { vid.play().catch(()=>{}); if (!viewedVideos.has(vidId)) { fetch(`/api/view/${vidId}`, {method: 'POST'}); viewedVideos.add(vidId); } } else { vid.pause(); vid.currentTime = 0; } }); }, {threshold: 0.6}); document.querySelectorAll('.video-section').forEach(s => observer.observe(s)); async function likeVideo(id) { {% if not current_user.is_authenticated %} window.location.href='/login'; return; {% endif %} const res = await fetch(`/api/like/${id}`, {method:'POST'}); const data = await res.json(); document.getElementById(`like-count-${id}`).innerText = data.count; const icon = document.getElementById(`like-icon-${id}`); data.action === 'liked' ? icon.classList.add('text-red-500') : icon.classList.remove('text-red-500'); icon.classList.add('pop-anim'); setTimeout(()=>icon.classList.remove('pop-anim'),300); } async function followUser(uid) { {% if not current_user.is_authenticated %} window.location.href='/login'; return; {% endif %} await fetch(`/api/follow/${uid}`, {method:'POST'}); document.querySelectorAll(`#follow-btn-${uid}`).forEach(b => b.style.display='none'); } async function openComments(vid) { currentVideoId = vid; replyingToId = null; cancelReply(); document.getElementById('mobile-nav').classList.add('hidden-nav'); document.getElementById('commentModal').classList.remove('hidden'); setTimeout(()=>document.getElementById('commentSheet').classList.remove('translate-y-full'),10); loadComments(); } async function loadComments() { const res = await fetch(`/api/comment/${currentVideoId}`); const data = await res.json(); const list = document.getElementById('commentsList'); list.innerHTML = ''; data.forEach(c => { const avatar = c.avatar ? `/static/avatars/${c.avatar}` : ''; const avatarHtml = avatar ? `<img src="${avatar}" class="w-8 h-8 rounded-full object-cover">` : `<div class="w-8 h-8 bg-gray-700 rounded-full flex items-center justify-center text-xs font-bold">${c.username[0].toUpperCase()}</div>`; const creatorBadge = c.is_video_owner ? '<span class="bg-blue-600 text-[10px] px-1 rounded ml-2">Yaratıcı</span>' : ''; const creatorLiked = c.liked_by_creator ? '<div class="text-[10px] text-red-400 mt-1 flex items-center gap-1">❤️ Yaratıcı beğendi</div>' : ''; let repliesHtml = ''; c.replies.forEach(r => { repliesHtml += `<div class="ml-10 mt-2 p-2 bg-white/5 rounded-lg text-sm border-l-2 border-gray-600"> <span class="font-bold text-gray-400 text-xs">@${r.username}</span> ${r.is_video_owner ? '<span class="bg-blue-600 text-[10px] px-1 rounded ml-1">Yaratıcı</span>' : ''} <div class="text-white/90">${r.text}</div> </div>`; }); list.innerHTML += `<div class="flex gap-3 animate__animated animate__fadeIn"> ${avatarHtml} <div class="flex-1"> <div class="flex justify-between items-start"> <div class="text-sm"> <span class="font-bold text-gray-300">@${c.username}</span> ${creatorBadge} <div class="text-white mt-0.5">${c.text}</div> ${creatorLiked} <button onclick="setReply(${c.id}, '@${c.username}')" class="text-xs text-gray-500 mt-2 hover:text-white">Yanıtla</button> </div> <div class="flex flex-col items-center"> <button onclick="likeComment(${c.id})" class="text-xs ${c.user_liked ? 'text-red-500' : 'text-gray-500'} hover:text-red-500">❤️</button> <span class="text-[10px] text-gray-500" id="comment-likes-${c.id}">${c.like_count}</span> </div> </div> ${repliesHtml} </div> </div>`; }); } function setReply(id, username) { replyingToId = id; document.getElementById('replyingTo').innerHTML = `Yanıtlanıyor: <span class="font-bold">${username}</span> <button onclick="cancelReply()" class="text-red-500 ml-2">X</button>`; document.getElementById('replyingTo').classList.remove('hidden'); document.getElementById('commentInput').focus(); } function cancelReply() { replyingToId = null; document.getElementById('replyingTo').classList.add('hidden'); } async function likeComment(cid) { const res = await fetch(`/api/like_comment/${cid}`, {method:'POST'}); loadComments(); } function closeComments() { document.getElementById('commentSheet').classList.add('translate-y-full'); setTimeout(()=>document.getElementById('commentModal').classList.add('hidden'),500); document.getElementById('mobile-nav').classList.remove('hidden-nav'); } async function postComment() { const txt = document.getElementById('commentInput').value; if(!txt) return; const payload = {text:txt}; if(replyingToId) payload.parent_id = replyingToId; const res = await fetch(`/api/comment/${currentVideoId}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}); const data = await res.json(); if(data.error) { alert(data.error); return; } document.getElementById('commentInput').value=''; cancelReply(); loadComments(); } async function bookmarkVideo(id) { {% if not current_user.is_authenticated %} window.location.href='/login'; return; {% endif %} const res = await fetch(`/api/bookmark/${id}`, {method:'POST'}); const data = await res.json(); const icon = document.getElementById(`bookmark-icon-${id}`); data.action === 'added' ? icon.classList.add('text-yellow-400') : icon.classList.remove('text-yellow-400'); } async function reportVideo(id) { const reason = prompt("Raporlama sebebi:"); if(!reason) return; await fetch(`/api/report/${id}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({reason:reason})}); alert("Rapor alındı."); } </script> {% endblock %} """

# --- UPLOAD.HTML ---
upload_html_code = """{% extends "layout.html" %} {% block content %} <div class="h-[100dvh] flex items-center justify-center p-4 pb-24 overflow-y-auto"> <form id="uploadForm" method="POST" enctype="multipart/form-data" class="glass p-6 rounded-3xl w-full max-w-lg flex flex-col gap-4 animate__animated animate__zoomIn"> <h2 class="text-2xl font-bold text-center">Hızlı Yükle</h2> <div class="border-2 border-dashed border-gray-600 rounded-xl p-4 relative bg-black min-h-[400px] flex items-center justify-center overflow-hidden cursor-pointer hover:border-red-500 transition"> <input type="file" name="file" id="videoFile" accept="video/*" class="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-30" required onchange="previewVideo(this)"> <div id="uploadPlaceholder" class="flex flex-col items-center pointer-events-none"> <span class="text-4xl mb-2">🎬</span> <p class="text-gray-400 text-sm">9:16 Video Seç</p> </div> <video id="previewPlayer" class="hidden w-full h-full object-contain z-10" autoplay muted loop></video> </div> <select name="category" class="p-4 rounded-xl bg-white/5 border border-white/10 outline-none text-gray-300"> <option value="Genel">Kategori Seç</option> <option value="Eğlence">Eğlence</option> <option value="Oyun">Oyun</option> <option value="Spor">Spor</option> <option value="Müzik">Müzik</option> <option value="Teknoloji">Teknoloji</option> <option value="Haber">Haber</option> </select> <textarea name="caption" placeholder="Açıklama... (Küfür yasak!)" class="p-4 rounded-xl bg-white/5 border border-white/10 outline-none h-24"></textarea> <button type="submit" id="submitBtn" class="bg-red-600 py-4 rounded-xl font-bold hover:bg-red-700 transition">Paylaş 🚀</button> </form> </div> <script> function previewVideo(input) { const file = input.files[0]; if (file) { const video = document.getElementById('previewPlayer'); const placeholder = document.getElementById('uploadPlaceholder'); const objectUrl = URL.createObjectURL(file); video.src = objectUrl; video.onloadedmetadata = function() { const ratio = video.videoWidth / video.videoHeight; if (ratio > 0.65) { alert("❌ HATA: Lütfen sadece 9:16 (Dikey) video yükleyin! (TikTok/Reels formatı)"); input.value = ""; video.src = ""; return; } if (video.duration > 210) { alert("⚠️ Video çok uzun! Maksimum 3.5 dakika olabilir."); input.value = ""; video.src = ""; return; } placeholder.classList.add('hidden'); video.classList.remove('hidden'); } } } </script> {% endblock %} """

# --- PROFILE.HTML ---
profile_html_code = """{% extends "layout.html" %} {% block content %} <div class="h-full overflow-y-auto w-full pb-24"> <div class="pt-20 pb-10 px-4 md:px-10 bg-gradient-to-b from-gray-900 to-black"> <div class="max-w-4xl mx-auto flex flex-col md:flex-row items-center gap-8"> <div class="relative group cursor-pointer" onclick="document.getElementById('avatarInput').click()"> {% if user.avatar %} <img src="/static/avatars/{{ user.avatar }}" class="w-32 h-32 md:w-40 md:h-40 rounded-full object-cover border-4 border-black ring-2 ring-white/20 animate__animated animate__zoomIn"> {% else %} <div class="w-32 h-32 md:w-40 md:h-40 bg-gradient-to-tr from-pink-600 to-purple-600 rounded-full flex items-center justify-center text-5xl font-bold border-4 border-black">{{ user.username[0]|upper }}</div> {% endif %} {% if current_user.id == user.id %} <div class="absolute inset-0 bg-black/50 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition backdrop-blur-sm"><span class="text-xs font-bold">Fotoğraf Değiştir</span></div> {% endif %} </div> {% if current_user.id == user.id %} <form id="avatarForm" action="/upload_avatar" method="POST" enctype="multipart/form-data" class="hidden"> <input type="file" name="avatar" id="avatarInput" accept="image/*" onchange="document.getElementById('avatarForm').submit()"> </form> {% endif %} <div class="text-center md:text-left flex-1 animate__animated animate__fadeInRight"> <div class="flex items-center justify-center md:justify-start gap-2 mb-2"> <h1 class="text-4xl font-bold tracking-tight">@{{ user.username }}</h1> {% if user.is_verified %}<span class="verified-badge w-6 h-6 text-sm shadow-[0_0_10px_#3b82f6]">✓</span>{% endif %} </div> <p class="text-gray-400 mb-6 font-light">{{ user.bio }}</p> <div class="flex justify-center md:justify-start gap-8 mb-6"> <div><span class="block font-bold text-2xl">{{ user.followers.count() }}</span><span class="text-xs text-gray-500 uppercase tracking-widest">Takipçi</span></div> <div><span class="block font-bold text-2xl">{{ videos|length }}</span><span class="text-xs text-gray-500 uppercase tracking-widest">Video</span></div> </div> <div class="flex gap-3 justify-center md:justify-start flex-wrap"> {% if current_user.is_authenticated and current_user.id != user.id %} <button id="profile-follow-btn" onclick="followUserFromProfile({{ user.id }})" class="{{ 'border border-white/20' if is_following else 'bg-red-600 shadow-lg' }} px-6 py-2.5 rounded-xl font-bold text-sm transition">{{ 'Takip Ediliyor' if is_following else 'Takip Et' }}</button> <a href="/messages/{{ user.id }}" class="bg-white/10 px-6 py-2.5 rounded-xl font-bold text-sm hover:bg-white/20 transition">Mesaj</a> {% endif %} {% if current_user.is_authenticated and current_user.id == user.id %} {% if user.is_admin %} <a href="/admin" class="bg-gradient-to-r from-blue-600 to-cyan-500 text-white px-6 py-2 rounded-xl font-bold text-sm shadow-lg hover:shadow-cyan-500/50 transition">🛡️ Admin Paneli</a> {% endif %} {% if user.is_verified %} <button class="bg-blue-600/10 text-blue-400 border border-blue-600/50 px-4 py-2 rounded-xl font-bold text-sm cursor-default">Onaylı Hesap ✓</button> {% else %} <form action="/apply_verification" method="POST" class="inline"><button class="bg-white/10 px-4 py-2 rounded-xl font-bold text-sm hover:bg-white/20">Mavi Tik İste</button></form> {% endif %} <a href="/logout" class="border border-red-500/50 text-red-500 px-6 py-2 rounded-xl font-bold text-sm hover:bg-red-500/10">Çıkış</a> {% endif %} </div> </div> </div> </div> <div class="max-w-5xl mx-auto px-4 mt-8" x-data="{ tab: 'videos' }"> <div class="flex border-b border-white/10 mb-6"> <button @click="tab = 'videos'" :class="{'border-b-2 border-white text-white': tab === 'videos', 'text-gray-500': tab !== 'videos'}" class="flex-1 py-4 font-bold transition">Videolar</button> {% if current_user.id == user.id %} <button @click="tab = 'saved'" :class="{'border-b-2 border-white text-white': tab === 'saved', 'text-gray-500': tab !== 'saved'}" class="flex-1 py-4 font-bold transition">Kaydedilenler</button> {% endif %} </div> <div x-show="tab === 'videos'" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 animate__animated animate__fadeIn"> {% for video in videos %} <a href="/watch/{{ video.id }}" class="aspect-[9/16] bg-gray-900 rounded-xl overflow-hidden relative group border border-white/5 hover:border-white/20 transition"><video src="{{ url_for('static', filename='uploads/' + video.filename) }}" class="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition duration-500 group-hover:scale-105"></video></a> {% endfor %} </div> {% if current_user.id == user.id %} <div x-show="tab === 'saved'" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 animate__animated animate__fadeIn" style="display: none;"> {% for video in bookmarked %} <a href="/watch/{{ video.id }}" class="aspect-[9/16] bg-gray-900 rounded-xl overflow-hidden relative group border border-yellow-500/30"><video src="{{ url_for('static', filename='uploads/' + video.filename) }}" class="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition"></video><div class="absolute top-2 right-2 text-xl drop-shadow-md">🔖</div></a> {% else %} <p class="col-span-full text-center text-gray-500 py-10">Henüz video kaydetmedin.</p> {% endfor %} </div> {% endif %} </div> </div> <script src="https://cdn.jsdelivr.net/gh/alpinejs/alpine@v2.x.x/dist/alpine.min.js"></script> <script> async function followUserFromProfile(uid) { const btn = document.getElementById('profile-follow-btn'); const res = await fetch(`/api/follow/${uid}`, {method:'POST'}); const data = await res.json(); if(data.action === 'followed') { btn.innerText = 'Takip Ediliyor'; btn.classList.remove('bg-red-600', 'shadow-lg'); btn.classList.add('border', 'border-white/20'); } else { btn.innerText = 'Takip Et'; btn.classList.add('bg-red-600', 'shadow-lg'); btn.classList.remove('border', 'border-white/20'); } } </script> {% endblock %} """

# --- CHAT DETAIL & LIST ---
chat_list_html_code = """{% extends "layout.html" %} {% block content %} <div class="h-full overflow-y-auto p-4 md:p-8 w-full max-w-2xl mx-auto pb-24"> <h1 class="text-3xl font-bold mb-8">Mesajlar</h1> <div class="space-y-2"> {% for chat in conversations %} <a href="/messages/{{ chat.user.id }}" class="flex items-center gap-4 glass p-4 rounded-xl hover:bg-white/5 transition animate__animated animate__fadeInUp"> {% if chat.user.avatar %}<img src="/static/avatars/{{ chat.user.avatar }}" class="w-12 h-12 rounded-full object-cover">{% else %}<div class="w-12 h-12 bg-gray-700 rounded-full flex items-center justify-center font-bold text-lg">{{ chat.user.username[0] | upper }}</div>{% endif %} <div class="flex-1"> <div class="flex justify-between"> <h3 class="font-bold">@{{ chat.user.username }}</h3> <span class="text-xs text-gray-500">{{ chat.last_msg.timestamp.strftime('%d %b') }}</span> </div> <p class="text-sm text-gray-400 truncate">{{ chat.last_msg.body }}</p> </div> {% if not chat.last_msg.is_read and chat.last_msg.recipient_id == current_user.id %} <div class="w-3 h-3 bg-red-600 rounded-full"></div> {% endif %} </a> {% else %} <div class="text-center py-10"> <p class="text-gray-500 mb-4">Henüz mesajlaşma yok.</p> <a href="/search" class="bg-white/10 px-6 py-2 rounded-full hover:bg-white/20">Arkadaş Ara</a> </div> {% endfor %} </div> </div> {% endblock %}"""
chat_detail_html_code = """{% extends "layout.html" %} {% block content %} <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script> <style> .md\\:hidden.fixed.bottom-0 { display: none !important; } </style> <div class="h-[100dvh] flex flex-col w-full max-w-3xl mx-auto md:border-x md:border-white/10 bg-black relative"> <div class="p-4 border-b border-white/10 flex items-center gap-4 glass bg-black/80 z-20 sticky top-0 backdrop-blur-md"> <a href="/messages" class="text-2xl hover:text-red-500 transition active:scale-90 p-2">←</a> <div class="relative"> {% if other_user.avatar %}<img src="/static/avatars/{{ other_user.avatar }}" class="w-10 h-10 rounded-full object-cover">{% else %}<div class="w-10 h-10 bg-gray-700 rounded-full flex items-center justify-center font-bold">{{ other_user.username[0] | upper }}</div>{% endif %} <div id="status-dot" class="absolute bottom-0 right-0 w-3 h-3 rounded-full border-2 border-[#0f0f12] {{ 'bg-green-500' if is_online else 'bg-gray-500' }}"></div> </div> <div> <h2 class="font-bold text-lg leading-none">@{{ other_user.username }}</h2> <span id="typing-indicator" class="text-xs text-green-400 font-bold hidden animate-pulse">yazıyor...</span> </div> </div> <div class="flex-1 overflow-y-auto p-4 space-y-3 flex flex-col scroll-smooth pb-4" id="msgContainer"> {% for msg in messages %} <div class="max-w-[75%] p-3 rounded-2xl text-sm animate__animated animate__fadeInUp {{ 'bg-gradient-to-r from-red-600 to-pink-600 text-white self-end rounded-tr-none' if msg.sender_id == current_user.id else 'bg-gray-800 text-gray-200 self-start rounded-tl-none' }}"> {{ msg.body }} <div class="text-[10px] opacity-70 text-right mt-1">{{ msg.timestamp.strftime('%H:%M') }}</div> </div> {% endfor %} </div> <div class="p-3 border-t border-white/10 glass bg-black z-30 sticky bottom-0 w-full mb-safe"> <div class="flex gap-2 items-center"> <input type="text" id="msgInput" placeholder="Mesaj yaz..." class="flex-1 bg-white/10 rounded-full px-5 py-3 outline-none focus:ring-1 focus:ring-red-500 transition text-white placeholder-gray-500" autocomplete="off"> <button onclick="sendMessage()" class="w-12 h-12 bg-red-600 rounded-full flex items-center justify-center hover:scale-110 transition shadow-lg shadow-red-600/30 active:scale-90 text-xl">➤</button> </div> </div> </div> <script> const socket = io(); const currentUserId = {{ current_user.id }}; const otherUserId = {{ other_user.id }}; const msgContainer = document.getElementById('msgContainer'); const msgInput = document.getElementById('msgInput'); const typingIndicator = document.getElementById('typing-indicator'); const statusDot = document.getElementById('status-dot'); setTimeout(() => msgContainer.scrollTop = msgContainer.scrollHeight, 100); socket.on('receive_message', function(data) { if (data.sender_id === otherUserId) { appendMessage(data.body, 'received', data.timestamp); typingIndicator.classList.add('hidden'); } }); socket.on('message_sent', function(data) { appendMessage(data.body, 'sent', data.timestamp); }); socket.on('display_typing', function(data) { if (data.sender_id === otherUserId) typingIndicator.classList.remove('hidden'); }); socket.on('hide_typing', function(data) { if (data.sender_id === otherUserId) typingIndicator.classList.add('hidden'); }); socket.on('user_status', function(data) { if (data.user_id === otherUserId) { statusDot.className = `absolute bottom-0 right-0 w-3 h-3 rounded-full border-2 border-[#0f0f12] ${data.status === 'online' ? 'bg-green-500' : 'bg-gray-500'}`; } }); function sendMessage() { const text = msgInput.value; if (!text) return; socket.emit('send_message', { recipient_id: otherUserId, body: text }); msgInput.value = ''; socket.emit('stop_typing', { recipient_id: otherUserId }); } function appendMessage(text, type, time) { const div = document.createElement('div'); const isSent = type === 'sent'; div.className = `max-w-[75%] p-3 rounded-2xl text-sm animate__animated animate__fadeInUp ${isSent ? 'bg-gradient-to-r from-red-600 to-pink-600 text-white self-end rounded-tr-none' : 'bg-gray-800 text-gray-200 self-start rounded-tl-none'}`; div.innerHTML = `${text}<div class="text-[10px] opacity-70 text-right mt-1">${time}</div>`; msgContainer.appendChild(div); msgContainer.scrollTop = msgContainer.scrollHeight; } let typingTimeout; msgInput.addEventListener('input', () => { socket.emit('typing', { recipient_id: otherUserId }); clearTimeout(typingTimeout); typingTimeout = setTimeout(() => { socket.emit('stop_typing', { recipient_id: otherUserId }); }, 1000); }); msgInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); }); window.visualViewport.addEventListener('resize', () => { msgContainer.scrollTop = msgContainer.scrollHeight; }); </script> {% endblock %} """

# --- ADMIN, SEARCH, NOTIF, LOGIN, REGISTER, EDIT ---
search_html_code = """{% extends "layout.html" %} {% block content %} <div class="h-full overflow-y-auto p-4 md:p-8 w-full pb-24"> <div class="max-w-3xl mx-auto mt-4 mb-8"> <form action="/search" method="GET" class="relative group"> <input type="text" name="q" value="{{ query if query else '' }}" placeholder="Kullanıcı veya içerik ara..." class="w-full bg-white/5 border border-white/10 rounded-full py-4 pl-14 pr-6 text-white outline-none focus:border-red-500 transition shadow-lg text-lg"> <span class="absolute left-5 top-1/2 -translate-y-1/2 text-2xl text-gray-400">🔍</span> </form> </div> {% if not query %} <div class="max-w-3xl mx-auto mb-8"> <h3 class="text-sm font-bold text-gray-500 uppercase mb-4 ml-2">Kategoriler</h3> <div class="grid grid-cols-2 md:grid-cols-4 gap-3"> <a href="/?category=Oyun" class="bg-gradient-to-br from-purple-900/50 to-purple-600/20 p-6 rounded-2xl border border-white/10 hover:border-purple-500/50 transition flex flex-col items-center gap-2 group"><span class="text-3xl group-hover:scale-110 transition">🎮</span><span class="font-bold">Oyun</span></a> <a href="/?category=Spor" class="bg-gradient-to-br from-green-900/50 to-green-600/20 p-6 rounded-2xl border border-white/10 hover:border-green-500/50 transition flex flex-col items-center gap-2 group"><span class="text-3xl group-hover:scale-110 transition">⚽</span><span class="font-bold">Spor</span></a> <a href="/?category=Eğlence" class="bg-gradient-to-br from-yellow-900/50 to-yellow-600/20 p-6 rounded-2xl border border-white/10 hover:border-yellow-500/50 transition flex flex-col items-center gap-2 group"><span class="text-3xl group-hover:scale-110 transition">😂</span><span class="font-bold">Eğlence</span></a> <a href="/?category=Müzik" class="bg-gradient-to-br from-pink-900/50 to-pink-600/20 p-6 rounded-2xl border border-white/10 hover:border-pink-500/50 transition flex flex-col items-center gap-2 group"><span class="text-3xl group-hover:scale-110 transition">🎵</span><span class="font-bold">Müzik</span></a> <a href="/?category=Teknoloji" class="bg-gradient-to-br from-blue-900/50 to-blue-600/20 p-6 rounded-2xl border border-white/10 hover:border-blue-500/50 transition flex flex-col items-center gap-2 group"><span class="text-3xl group-hover:scale-110 transition">💻</span><span class="font-bold">Teknoloji</span></a> <a href="/?category=Haber" class="bg-gradient-to-br from-gray-800/50 to-gray-600/20 p-6 rounded-2xl border border-white/10 hover:border-white/50 transition flex flex-col items-center gap-2 group"><span class="text-3xl group-hover:scale-110 transition">📰</span><span class="font-bold">Haber</span></a> </div> </div> {% endif %} {% if query %} <h2 class="text-xl font-bold mb-4 px-2 text-gray-300">"{{ query }}" sonuçları:</h2> {% if users %} <div class="grid grid-cols-1 md:grid-cols-2 gap-2 mb-8"> {% for user in users %} <a href="{{ url_for('profile', username=user.username) }}" class="flex items-center gap-4 bg-white/5 p-4 rounded-xl hover:bg-white/10 transition border border-white/5 animate__animated animate__fadeIn"> {% if user.avatar %}<img src="/static/avatars/{{ user.avatar }}" class="w-12 h-12 rounded-full object-cover">{% else %}<div class="w-12 h-12 bg-gray-700 rounded-full flex items-center justify-center font-bold text-lg">{{ user.username[0] | upper }}</div>{% endif %} <div><div class="font-bold flex items-center gap-1">@{{ user.username }} {% if user.is_verified %}<span class="verified-badge">✓</span>{% endif %}</div><div class="text-xs text-gray-400">{{ user.followers.count() }} Takipçi</div></div> </a> {% endfor %} </div> {% endif %} {% if videos %} <div class="grid grid-cols-2 md:grid-cols-4 gap-3"> {% for video in videos %} <a href="/watch/{{ video.id }}" class="aspect-[9/16] bg-gray-800 rounded-xl overflow-hidden relative group border border-white/10 animate__animated animate__fadeIn"> <video src="{{ url_for('static', filename='uploads/' + video.filename) }}" class="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition"></video> <div class="absolute bottom-2 left-2 text-xs font-bold text-white shadow-black drop-shadow-md">👁️ {{ video.views }}</div> </a> {% endfor %} </div> {% endif %} {% endif %} </div> {% endblock %}"""
notifications_html_code = """{% extends "layout.html" %} {% block content %} <div class="h-full overflow-y-auto p-4 md:p-8 w-full max-w-2xl mx-auto pb-24"> <h1 class="text-3xl font-bold mb-8">Bildirimler</h1> <div class="space-y-2"> {% for notif in notifications %} <div class="flex items-center gap-4 glass p-4 rounded-xl animate__animated animate__fadeInLeft"> <div class="w-10 h-10 bg-gray-700 rounded-full flex items-center justify-center font-bold">{{ notif.sender.username[0] | upper }}</div> <div class="flex-1"> <p class="text-sm"> <span class="font-bold">@{{ notif.sender.username }}</span> {% if notif.type == 'like' %} videonu beğendi ❤️ {% elif notif.type == 'follow' %} seni takip etmeye başladı 🚀 {% elif notif.type == 'comment' %} videona yorum yaptı 💬 {% elif notif.type == 'gift' %} sana {{ notif.amount }} Coin gönderdi 🎁 {% elif notif.type == 'system_approve' %} <span class="text-blue-400">Mavi Tik Başvurunuz Onaylandı! 🏅</span> {% endif %} </p> <span class="text-xs text-gray-500">{{ notif.timestamp.strftime('%H:%M') }}</span> </div> {% if notif.post_id %} <a href="/watch/{{ notif.post_id }}" class="w-10 h-10 bg-gray-800 rounded overflow-hidden border border-white/20"><div class="w-full h-full bg-red-900/50 flex items-center justify-center text-xs">▶</div></a> {% endif %} </div> {% else %} <p class="text-center text-gray-500">Henüz bildirim yok.</p> {% endfor %} </div> </div> {% endblock %}"""
admin_html_code = """{% extends "layout.html" %} {% block content %} <div class="h-full overflow-y-auto p-4 md:p-8 w-full pb-24"> <h1 class="text-4xl font-bold mb-8 text-transparent bg-clip-text bg-gradient-to-r from-red-500 to-purple-600">Admin Kalesi 🛡️</h1> <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-10"> <div class="glass p-6 rounded-2xl"><h3 class="text-gray-400 mb-2">Kullanıcı</h3><p class="text-4xl font-bold">{{ stats.users }}</p></div> <div class="glass p-6 rounded-2xl"><h3 class="text-gray-400 mb-2">Video</h3><p class="text-4xl font-bold">{{ stats.videos }}</p></div> <div class="glass p-6 rounded-2xl"><h3 class="text-gray-400 mb-2">Beğeni</h3><p class="text-4xl font-bold">{{ stats.likes }}</p></div> <div class="glass p-6 rounded-2xl border-red-500/50"><h3 class="text-red-400 mb-2">Raporlar</h3><p class="text-4xl font-bold text-red-500">{{ stats.reports }}</p></div> </div> {% if reports %} <div class="bg-red-900/10 rounded-2xl p-6 border border-red-500/30 mb-8"> <h2 class="text-xl font-bold mb-4 text-red-400">🚨 Şikayet Edilen İçerikler</h2> <div class="space-y-3"> {% for r in reports %} <div class="flex justify-between items-center bg-black/40 p-4 rounded-lg border border-red-500/20"> <div class="flex items-center gap-4"> <video src="/static/uploads/{{ r.video.filename }}" class="w-16 h-24 object-cover rounded bg-black"></video> <div> <div class="font-bold text-red-300">Sebep: {{ r.reason }}</div> <div class="text-xs text-gray-400">Raporlayan: @{{ r.reporter.username }}</div> </div> </div> <div class="flex gap-2"> <a href="/admin/delete_video/{{ r.video.id }}" onclick="return confirm('SİL?')" class="bg-red-600 px-4 py-2 rounded font-bold hover:bg-red-700">Sil</a> <a href="/admin/dismiss_report/{{ r.id }}" class="bg-gray-600 px-4 py-2 rounded font-bold hover:bg-gray-500">Es Geç</a> </div> </div> {% endfor %} </div> </div> {% endif %} <div class="grid grid-cols-1 lg:grid-cols-2 gap-8"> <div class="glass rounded-2xl p-6"> <h2 class="text-xl font-bold mb-4">Son Kullanıcılar</h2> {% for u in users %} <div class="flex justify-between items-center bg-black/20 p-2 rounded mb-2"> <span>@{{ u.username }}</span> {% if not u.is_admin %}<a href="/admin/delete_user/{{ u.id }}" class="text-red-500 text-xs border border-red-500 px-2 py-1 rounded hover:bg-red-500 hover:text-white">BAN</a>{% endif %} </div> {% endfor %} </div> <div class="glass rounded-2xl p-6"> <h2 class="text-xl font-bold mb-4">Son Videolar</h2> {% for v in videos %} <div class="flex justify-between items-center bg-black/20 p-2 rounded mb-2"> <span class="truncate w-40">{{ v.caption }}</span> <a href="/admin/delete_video/{{ v.id }}" class="text-red-500">🗑️</a> </div> {% endfor %} </div> </div> </div> {% endblock %} """
login_html_code = """{% extends "layout.html" %} {% block content %} <div class="h-[100dvh] flex items-center justify-center p-4 relative overflow-hidden"> <div class="absolute top-20 left-20 w-72 h-72 bg-purple-600/20 rounded-full blur-[100px] animate-pulse"></div> <div class="absolute bottom-20 right-20 w-72 h-72 bg-red-600/20 rounded-full blur-[100px] animate-pulse"></div> <form method="POST" class="glass p-10 rounded-3xl w-full max-w-sm flex flex-col gap-6 relative z-10 animate__animated animate__fadeInUp"> <h2 class="text-3xl font-bold text-center">Giriş Yap</h2> <input type="text" name="username" placeholder="Kullanıcı Adı" class="p-4 rounded-xl bg-white/5 border border-white/10 outline-none" required> <input type="password" name="password" placeholder="Şifre" class="p-4 rounded-xl bg-white/5 border border-white/10 outline-none" required> <button type="submit" class="bg-gradient-to-r from-red-600 to-purple-600 py-4 rounded-xl font-bold shadow-lg hover:scale-[1.02] transition">Giriş</button> <a href="/register" class="text-center text-sm text-gray-500 hover:text-white transition">Kayıt Ol</a> </form> </div> {% endblock %}"""
register_html_code = """{% extends "layout.html" %} {% block content %} <div class="h-[100dvh] flex items-center justify-center p-4 relative overflow-hidden"> <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-blue-600/20 rounded-full blur-[120px] animate-pulse"></div> <form method="POST" class="glass p-10 rounded-3xl w-full max-w-sm flex flex-col gap-6 relative z-10 animate__animated animate__fadeInUp"> <h2 class="text-3xl font-bold text-center">Kayıt Ol</h2> <input type="text" name="username" placeholder="Kullanıcı Adı" class="p-4 rounded-xl bg-white/5 border border-white/10 outline-none" required> <input type="password" name="password" placeholder="Şifre" class="p-4 rounded-xl bg-white/5 border border-white/10 outline-none" required> <button type="submit" class="bg-white text-black py-4 rounded-xl font-bold hover:scale-[1.02] transition">Hesap Oluştur</button> <p class="text-xs text-center text-gray-500">Not: 'admin' kullanıcı adıyla kayıt olursan Yönetici olursun.</p> </form> </div> {% endblock %}"""
edit_video_html_code = """{% extends "layout.html" %} {% block content %} <div class="h-[100dvh] flex items-center justify-center p-4"> <form method="POST" class="glass p-8 rounded-2xl w-full max-w-md flex flex-col gap-6 animate__animated animate__fadeIn"> <h2 class="text-2xl font-bold text-center">Düzenle</h2> <textarea name="caption" class="p-4 rounded-xl bg-white/5 border border-white/10 outline-none">{{ video.caption }}</textarea> <button type="submit" class="bg-blue-600 py-3 rounded-xl font-bold">Kaydet</button> </form> </div> {% endblock %}"""

def create_project_v23():
    directories = ["templates", "static", "static/uploads", "static/avatars"]
    for d in directories:
        if not os.path.exists(d): os.makedirs(d)

    files = {
        "app.py": app_py_code,
        "templates/layout.html": layout_html_code,
        "templates/home.html": home_html_code,
        "templates/feed.html": feed_html_code,
        "templates/profile.html": profile_html_code,
        "templates/admin.html": admin_html_code,
        "templates/upload.html": upload_html_code,
        "templates/search.html": search_html_code,
        "templates/notifications.html": notifications_html_code,
        "templates/chat_list.html": chat_list_html_code,
        "templates/chat_detail.html": chat_detail_html_code,
        "templates/login.html": login_html_code,
        "templates/register.html": register_html_code,
        "templates/edit_video.html": edit_video_html_code
    }

    for f, c in files.items():
        with open(f, "w", encoding="utf-8") as file:
            file.write(c)
            print(f"✅ {f}")

    print("\n💎 VETRICO v23.1 (SMART NOTIF & BUG FIX COMPLETE) HAZIR!")
    print("1. 'python app.py' çalıştır.")
    print("2. Telefondan girip bildirim kutusunu test et (artık taşmaz ve kaybolur).")

if __name__ == "__main__":
    create_project_v23()