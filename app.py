import os
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
        if re.search(r'\b' + re.escape(word) + r'\b', text): return True
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
