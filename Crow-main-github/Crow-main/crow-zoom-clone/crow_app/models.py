# crow_app/models.py
from django.db import models
from django.contrib.auth.models import User
import uuid
from django.utils import timezone
from datetime import timedelta

class Room(models.Model):
    ROOM_TYPES = [('public', 'Public Room'), ('private', 'Private Room')]
    
    name = models.CharField(max_length=200)
    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hosted_rooms')
    room_type = models.CharField(choices=ROOM_TYPES, default='public', max_length=10)
    password = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return self.name

class UserClass(models.Model):
    """Represents a class/group that users can belong to"""
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)  # e.g., "CS101", "MATH202"
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_classes')
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name_plural = "User Classes"
    
    def __str__(self):
        return f"{self.code} - {self.name}"


class ClassMembership(models.Model):
    """Tracks which users belong to which classes"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='class_memberships')
    user_class = models.ForeignKey(UserClass, on_delete=models.CASCADE, related_name='members')
    date_joined = models.DateTimeField(auto_now_add=True)
    role = models.CharField(max_length=20, choices=[
        ('student', 'Student'),
        ('teacher', 'Teacher'),
        ('assistant', 'Assistant'),
        ('member', 'Member')
    ], default='student')
    
    class Meta:
        unique_together = ['user', 'user_class']
    
    def __str__(self):
        return f"{self.user.username} in {self.user_class.code}"



class Meeting(models.Model):
    title = models.CharField(max_length=200)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='meetings')
    scheduled_time = models.DateTimeField()
    duration = models.IntegerField(default=60)
    created_at = models.DateTimeField(auto_now_add=True)
    participants = models.ManyToManyField(User, through='MeetingParticipant')
    allowed_classes = models.ManyToManyField(UserClass, blank=True, related_name='meetings')
    restrict_to_classes = models.BooleanField(default=False) 
    def __str__(self):
        return self.title

class MeetingParticipant(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ['user', 'meeting']

class Contact(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contacts_owner')
    contact_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contacts')
    added_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'contact_user']

class UserProfile(models.Model):
    THEME_CHOICES = [('light', 'Light'), ('dark', 'Dark'), ('auto', 'Auto')]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    profile_picture = models.ImageField(upload_to='profiles/', null=True, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    timezone = models.CharField(max_length=50, default='UTC')
    phone_number = models.CharField(max_length=20, blank=True)
    company = models.CharField(max_length=100, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    theme_preference = models.CharField(choices=THEME_CHOICES, default='light', max_length=20)
    default_join_with_video = models.BooleanField(default=True)
    default_mute_on_join = models.BooleanField(default=False)
    default_meeting_duration = models.IntegerField(default=60)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username}'s Profile"

# NEW: WebRTC Meeting Room Model
class MeetingRoom(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name='webrtc_hosted_rooms')
    participants = models.ManyToManyField(User, related_name='webrtc_joined_rooms', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    max_participants = models.IntegerField(default=10)
    
    def __str__(self):
        return f"{self.name} (Host: {self.host.username})"
class UserSession(models.Model):
    """Track user login sessions"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions')
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    device_type = models.CharField(max_length=50, blank=True)  # Desktop, Mobile, Tablet
    browser = models.CharField(max_length=50, blank=True)
    location = models.CharField(max_length=200, blank=True)  # City, Country
    
    login_time = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    logout_time = models.DateTimeField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-login_time']
    
    def __str__(self):
        return f"{self.user.username} - {self.login_time.strftime('%Y-%m-%d %H:%M')}"
    
    def duration(self):
        """Get session duration"""
        end_time = self.logout_time or timezone.now()
        return end_time - self.login_time
    
    def is_online(self):
        """Check if session is currently active (last activity within 5 minutes)"""
        if not self.is_active:
            return False
        return (timezone.now() - self.last_activity) < timedelta(minutes=5)


class MeetingSession(models.Model):
    """Track individual meeting participation sessions"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='meeting_sessions')
    meeting = models.ForeignKey('Meeting', on_delete=models.CASCADE, related_name='sessions')
    room = models.ForeignKey('Room', on_delete=models.CASCADE, related_name='sessions')
    
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    
    # Technical details
    connection_quality = models.CharField(max_length=20, choices=[
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
    ], default='good')
    
    # Participation metrics
    video_enabled_duration = models.IntegerField(default=0)  # seconds
    audio_enabled_duration = models.IntegerField(default=0)  # seconds
    screen_shared_duration = models.IntegerField(default=0)  # seconds
    
    # Device info
    device_type = models.CharField(max_length=50, blank=True)
    browser = models.CharField(max_length=50, blank=True)
    
    class Meta:
        ordering = ['-joined_at']
    
    def __str__(self):
        return f"{self.user.username} in {self.meeting.title}"
    
    def duration(self):
        """Get session duration"""
        end_time = self.left_at or timezone.now()
        return end_time - self.joined_at
    
    def is_active(self):
        """Check if user is currently in meeting"""
        return self.left_at is None


class UserActivity(models.Model):
    """Track user activities for analytics"""
    ACTIVITY_TYPES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('meeting_created', 'Meeting Created'),
        ('meeting_joined', 'Meeting Joined'),
        ('meeting_left', 'Meeting Left'),
        ('team_created', 'Team Created'),
        ('team_joined', 'Team Joined'),
        ('contact_added', 'Contact Added'),
        ('settings_updated', 'Settings Updated'),
        ('profile_updated', 'Profile Updated'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPES)
    description = models.TextField(blank=True)
    
    # Related objects (optional)
    meeting = models.ForeignKey('Meeting', null=True, blank=True, on_delete=models.SET_NULL)
    room = models.ForeignKey('Room', null=True, blank=True, on_delete=models.SET_NULL)
    team = models.ForeignKey('UserClass', null=True, blank=True, on_delete=models.SET_NULL)
    
    # Metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = "User Activities"
    
    def __str__(self):
        return f"{self.user.username} - {self.activity_type} at {self.timestamp}"


class OnlineUser(models.Model):
    """Track currently online users (real-time presence)"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='online_status')
    last_seen = models.DateTimeField(auto_now=True)
    current_page = models.CharField(max_length=200, blank=True)
    is_in_meeting = models.BooleanField(default=False)
    current_meeting = models.ForeignKey('Meeting', null=True, blank=True, on_delete=models.SET_NULL)
    
    class Meta:
        verbose_name = "Online User"
        verbose_name_plural = "Online Users"
    
    def __str__(self):
        return f"{self.user.username} - Last seen: {self.last_seen}"
    
    def is_online(self):
        """User is online if last_seen within 2 minutes"""
        return (timezone.now() - self.last_seen) < timedelta(minutes=2)
    
    @staticmethod
    def get_online_count():
        """Get count of currently online users"""
        threshold = timezone.now() - timedelta(minutes=2)
        return OnlineUser.objects.filter(last_seen__gte=threshold).count()
    
    @staticmethod
    def get_online_users():
        """Get list of currently online users"""
        threshold = timezone.now() - timedelta(minutes=2)
        return OnlineUser.objects.filter(last_seen__gte=threshold).select_related('user')
class AdminRole(models.Model):
    """
    Extended permissions for admin users
    Allows role-based access to admin dashboard
    """
    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('analytics_admin', 'Analytics Admin'),
        ('support_admin', 'Support Admin'),
        ('moderator', 'Moderator'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='admin_role')
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='moderator')
    
    # Permissions
    can_view_analytics = models.BooleanField(default=True)
    can_manage_users = models.BooleanField(default=False)
    can_manage_teams = models.BooleanField(default=False)
    can_view_all_meetings = models.BooleanField(default=False)
    can_delete_content = models.BooleanField(default=False)
    can_manage_admins = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Admin Role"
        verbose_name_plural = "Admin Roles"
    
    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"
    
    def is_super_admin(self):
        return self.role == 'super_admin'
    
    def save(self, *args, **kwargs):
        # Auto-set permissions based on role
        if self.role == 'super_admin':
            self.can_view_analytics = True
            self.can_manage_users = True
            self.can_manage_teams = True
            self.can_view_all_meetings = True
            self.can_delete_content = True
            self.can_manage_admins = True
        elif self.role == 'analytics_admin':
            self.can_view_analytics = True
            self.can_view_all_meetings = True
        elif self.role == 'support_admin':
            self.can_view_analytics = True
            self.can_manage_users = True
        
        super().save(*args, **kwargs)


class SiteStatistics(models.Model):
    """
    Daily snapshot of site statistics for trend analysis
    """
    date = models.DateField(unique=True, default=timezone.now)
    
    # User metrics
    total_users = models.IntegerField(default=0)
    new_users_today = models.IntegerField(default=0)
    active_users_today = models.IntegerField(default=0)
    
    # Meeting metrics
    total_meetings = models.IntegerField(default=0)
    meetings_today = models.IntegerField(default=0)
    total_meeting_minutes = models.BigIntegerField(default=0)
    
    # Team metrics
    total_teams = models.IntegerField(default=0)
    teams_created_today = models.IntegerField(default=0)
    
    # Activity metrics
    total_logins_today = models.IntegerField(default=0)
    peak_concurrent_users = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-date']
        verbose_name_plural = "Site Statistics"
    
    def __str__(self):
        return f"Stats for {self.date}"
    
    @classmethod
    def generate_today_stats(cls):
        """Generate statistics for today"""
        from django.contrib.auth.models import User
        from datetime import timedelta
        
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)
        
        # User stats
        total_users = User.objects.count()
        new_users_today = User.objects.filter(date_joined__date=today).count()
        active_users_today = UserSession.objects.filter(
            login_time__date=today
        ).values('user').distinct().count()
        
        # Meeting stats
        total_meetings = Meeting.objects.count()
        meetings_today = Meeting.objects.filter(created_at__date=today).count()
        total_meeting_minutes = MeetingSession.objects.filter(
            left_at__isnull=False
        ).aggregate(
            total=models.Sum(
                models.F('left_at') - models.F('joined_at')
            )
        )['total'] or timedelta(0)
        
        # Team stats
        total_teams = UserClass.objects.count()
        teams_created_today = UserClass.objects.filter(created_at__date=today).count()
        
        # Activity stats
        total_logins_today = UserActivity.objects.filter(
            activity_type='login',
            timestamp__date=today
        ).count()
        
        # Create or update stats
        stats, created = cls.objects.update_or_create(
            date=today,
            defaults={
                'total_users': total_users,
                'new_users_today': new_users_today,
                'active_users_today': active_users_today,
                'total_meetings': total_meetings,
                'meetings_today': meetings_today,
                'total_meeting_minutes': int(total_meeting_minutes.total_seconds() // 60),
                'total_teams': total_teams,
                'teams_created_today': teams_created_today,
                'total_logins_today': total_logins_today,
            }
        )
        
        return stats


# Helper function to check if user is admin
def is_admin(user):
    """Check if user has admin role"""
    try:
        return hasattr(user, 'admin_role') and user.admin_role is not None
    except:
        return False


def require_admin_permission(permission):
    """Decorator to check admin permissions"""
    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            if not is_admin(request.user):
                messages.error(request, "You don't have admin access")
                return redirect('home')
            
            admin_role = request.user.admin_role
            
            # Check specific permission
            if permission and not getattr(admin_role, permission, False):
                messages.error(request, "You don't have permission for this action")
                return redirect('admin_dashboard')
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator