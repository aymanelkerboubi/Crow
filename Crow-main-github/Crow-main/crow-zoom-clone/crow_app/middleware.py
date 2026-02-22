# crow_app/middleware.py - SESSION TRACKING MIDDLEWARE

from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from .models import UserSession, OnlineUser, UserActivity
import user_agents

class SessionTrackingMiddleware(MiddlewareMixin):
    """
    Middleware to track user sessions automatically
    """
    
    def process_request(self, request):
        """Track every request"""
        
        if request.user.is_authenticated:
            # Get or create session
            session_key = request.session.session_key
            
            if session_key:
                # Update or create user session
                user_session, created = UserSession.objects.get_or_create(
                    user=request.user,
                    session_key=session_key,
                    defaults={
                        'ip_address': self.get_client_ip(request),
                        'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                        'device_type': self.get_device_type(request),
                        'browser': self.get_browser(request),
                    }
                )
                
                # Update last activity
                if not created:
                    user_session.last_activity = timezone.now()
                    user_session.save(update_fields=['last_activity'])
                
                # Update online status
                online_user, _ = OnlineUser.objects.update_or_create(
                    user=request.user,
                    defaults={
                        'current_page': request.path,
                        'last_seen': timezone.now()
                    }
                )
    
    def get_client_ip(self, request):
        """Get user's IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_device_type(self, request):
        """Detect device type"""
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        ua = user_agents.parse(user_agent)
        
        if ua.is_mobile:
            return 'Mobile'
        elif ua.is_tablet:
            return 'Tablet'
        elif ua.is_pc:
            return 'Desktop'
        else:
            return 'Unknown'
    
    def get_browser(self, request):
        """Detect browser"""
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        ua = user_agents.parse(user_agent)
        return f"{ua.browser.family} {ua.browser.version_string}"


class ActivityTrackingMiddleware(MiddlewareMixin):
    """
    Track important user activities
    """
    
    def process_response(self, request, response):
        """Log activities based on the view accessed"""
        
        if request.user.is_authenticated and response.status_code == 200:
            # Only track successful requests
            
            # Track specific activities based on URL patterns
            if request.method == 'POST':
                path = request.path
                
                # Login
                if 'login' in path:
                    self.log_activity(request.user, 'login', 'User logged in', request)
                
                # Meeting actions
                elif 'meeting' in path or 'room' in path:
                    if 'create' in path:
                        self.log_activity(request.user, 'meeting_created', 'Created a meeting', request)
                
                # Team actions
                elif 'class' in path or 'team' in path:
                    if 'create' in path:
                        self.log_activity(request.user, 'team_created', 'Created a team', request)
                    elif 'join' in path:
                        self.log_activity(request.user, 'team_joined', 'Joined a team', request)
                
                # Settings
                elif 'settings' in path:
                    self.log_activity(request.user, 'settings_updated', 'Updated settings', request)
        
        return response
    
    def log_activity(self, user, activity_type, description, request):
        """Helper to log activity"""
        try:
            UserActivity.objects.create(
                user=user,
                activity_type=activity_type,
                description=description,
                ip_address=self.get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        except Exception as e:
            # Don't break the request if activity logging fails
            print(f"Failed to log activity: {e}")
    
    def get_client_ip(self, request):
        """Get user's IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip