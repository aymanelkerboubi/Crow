# FIXED views.py - Copy this to replace your current views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, logout as auth_logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import IntegrityError  # FIX: Added missing import
from django.db.models import Count, Avg, Sum,Q  # FIX: Added for query filtering
from .models import ClassMembership, Room, Meeting, Contact, UserClass, UserProfile, MeetingRoom
import json
import requests
from django.views.decorators.csrf import csrf_exempt
from .ai_service import gemini_service
from .models import UserSession, MeetingSession, UserActivity, OnlineUser


# ===== AI CHATBOT VIEWS =====
@login_required
def ai_chatbot(request):
    return render(request, "ai_chatbot.html")


@csrf_exempt
@login_required
def ai_chat_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        message = data.get("message", "").strip()

        if not message:
            return JsonResponse({"error": "Message required"}, status=400)

        # User context
        context = {"username": request.user.username}

        teams = ClassMembership.objects.filter(
            user=request.user
        ).select_related("user_class")[:5]

        context["teams"] = [
            {
                "name": t.user_class.name,
                "code": t.user_class.code,
                "role": t.role,
            }
            for t in teams
        ]

        response = gemini_service.get_chat_response(message, context)

        return JsonResponse({
            "response": response,
            "ai_status": "online" if not gemini_service.use_fallback else "fallback"
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
def get_ai_response(message, user):
    """Get response from AI service"""
    message_lower = message.lower()
    
    # Meeting-related responses
    if any(word in message_lower for word in ['meeting', 'schedule', 'calendar']):
        return "I can help you with meetings! You can schedule meetings from the Calendar page, or create instant rooms from the dashboard."
    
    elif any(word in message_lower for word in ['video', 'camera', 'microphone']):
        return "For video settings, check your browser permissions. Make sure your camera and microphone are allowed for Crow."
    
    elif any(word in message_lower for word in ['class', 'join class', 'create class']):
        return "You can create or join classes from the Classes page. Classes help organize meetings by groups!"
    
    elif any(word in message_lower for word in ['contact', 'friend', 'invite']):
        return "You can add contacts from the Contacts page. Once added, you can invite them to meetings directly."
    
    elif any(word in message_lower for word in ['hello', 'hi', 'hey']):
        return f"Hello {user.username}! 👋 I'm Crow's AI assistant. How can I help you today?"
    
    elif any(word in message_lower for word in ['help', 'support']):
        return "I can help you with: scheduling meetings, technical issues, contact management, classes, and using Crow features."
    
    elif any(word in message_lower for word in ['thank', 'thanks']):
        return "You're welcome! Let me know if you need anything else. 🎯"
    
    elif any(word in message_lower for word in ['bye', 'goodbye']):
        return "Goodbye! Have a great day! 👋"
    
    # Default response
    return f"I understand you're asking about: '{message}'. I'm here to help with video meetings, scheduling, contacts, classes, and technical support. Could you tell me more?"

# ===== HOME VIEW =====
def home(request):
    if not request.user.is_authenticated:
        return redirect('login')
    
    # Get user profile
    profile = None
    if hasattr(request.user, 'profile'):
        profile = request.user.profile
    
    recent_meetings = Meeting.objects.filter(
        participants=request.user
    ).order_by('-scheduled_time')[:5]
    
    upcoming_meetings = Meeting.objects.filter(
        scheduled_time__gte=timezone.now(),
        participants=request.user
    ).order_by('scheduled_time')[:5]
    
    context = {
        'profile': profile,
        'recent_meetings': recent_meetings,
        'upcoming_meetings': upcoming_meetings,
    }
    return render(request, 'home.html', context)


# ===== HELPER FUNCTIONS =====
def _create_meeting(room, host, title=None, scheduled_time=None, duration=None, participants=None):
    """Helper to create a meeting"""
    if title is None:
        title = f"Meeting - {room.name}"
    if scheduled_time is None:
        scheduled_time = timezone.now()
    if duration is None:
        try:
            duration = host.profile.default_meeting_duration
        except:
            duration = 60

    meeting = Meeting.objects.create(
        title=title,
        room=room,
        scheduled_time=scheduled_time,
        duration=duration,
    )
    meeting.participants.add(host)
    if participants:
        for p in participants:
            try:
                meeting.participants.add(p)
            except:
                pass
    return meeting

# ===== AUTHENTICATION VIEWS =====
def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('home')
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = AuthenticationForm()
    return render(request, 'login.html', {'form': form})

def register_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            
            # Create user profile
            UserProfile.objects.create(user=user)
            
            login(request, user)
            messages.success(request, 'Account created successfully!')
            return redirect('home')
    else:
        form = UserCreationForm()
    return render(request, 'register.html', {'form': form})

def logout_view(request):
    """Log out the user"""
    auth_logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('home')

# ===== PROFILE & SETTINGS =====
@login_required
def settings_view(request):
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        bio = request.POST.get('bio', '').strip()
        default_join_with_video = True if request.POST.get('default_join_with_video') else False
        default_mute_on_join = True if request.POST.get('default_mute_on_join') else False

        if email:
            request.user.email = email
            request.user.save()

        profile.bio = bio
        profile.default_join_with_video = default_join_with_video
        profile.default_mute_on_join = default_mute_on_join

        if 'profile_picture' in request.FILES:
            profile.profile_picture = request.FILES['profile_picture']

        profile.save()

        messages.success(request, 'Settings updated successfully!')
        return redirect('settings')

    return render(request, 'settings.html', {'profile': profile})

@login_required
def profile_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, 'settings.html', {'profile': profile})

# ===== MEETING & ROOM VIEWS =====
@login_required
def create_room(request):
    """Create a new room"""
    if request.method == 'POST':
        name = request.POST.get('name')
        room_type = request.POST.get('room_type', 'public')
        password = request.POST.get('password')
        
        if not name:
            messages.error(request, 'Room name is required')
            return redirect('create_room')
        
        room = Room.objects.create(
            name=name,
            host=request.user,
            room_type=room_type,
            password=password if room_type == 'private' else None
        )
        
        # Create instant meeting
        _create_meeting(room=room, host=request.user)
        
        messages.success(request, f'Room "{name}" created successfully!')
        return redirect('room_detail', room_id=room.id)
    
    return render(request, 'create_room.html')

@login_required
def room_detail(request, room_id):
    """View room details"""
    room = get_object_or_404(Room, id=room_id)
    
    # Check password for private rooms
    if room.room_type == 'private' and room.host != request.user:
        if request.method == 'POST':
            password = request.POST.get('password')
            if password != room.password:
                messages.error(request, 'Incorrect password')
                return redirect('home')
        else:
            return render(request, 'room_password.html', {'room': room})
    
    meetings = Meeting.objects.filter(room=room).order_by('-scheduled_time')
    
    context = {
        'room': room,
        'meetings': meetings,
    }
    return render(request, 'room.html', context)

@login_required
def calendar_view(request):
    """Calendar view for scheduling and managing meetings"""
    from collections import defaultdict
    import json
    from datetime import datetime
    
    # Get user's teams
    user_classes = ClassMembership.objects.filter(user=request.user).select_related('user_class')
    
    # Handle POST requests
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # DELETE MEETING
        if action == 'delete':
            meeting_id = request.POST.get('meeting_id')
            try:
                meeting = Meeting.objects.get(id=meeting_id)
                
                # Check if user is the host (room owner)
                if meeting.room.host == request.user:
                    meeting_title = meeting.title
                    meeting.delete()
                    messages.success(request, f'Meeting "{meeting_title}" deleted successfully!')
                else:
                    messages.error(request, 'You do not have permission to delete this meeting')
            except Meeting.DoesNotExist:
                messages.error(request, 'Meeting not found')
            
            return redirect('calendar')
        
        # CREATE MEETING
        else:
            title = request.POST.get('title')
            scheduled_time = request.POST.get('scheduled_time')
            duration = request.POST.get('duration', 60)
            restrict_to_classes = request.POST.get('restrict_to_classes') == 'on'
            selected_class_ids = request.POST.getlist('allowed_classes')
            
            if not title or not scheduled_time:
                messages.error(request, 'Title and scheduled time are required')
                return redirect('calendar')
            
            try:
                # Create room for the meeting
                room = Room.objects.create(
                    name=f"{title} - Room",
                    host=request.user,
                    room_type='public'
                )
                
                # Create meeting
                meeting = Meeting.objects.create(
                    title=title,
                    room=room,
                    scheduled_time=scheduled_time,
                    duration=int(duration),
                    restrict_to_classes=restrict_to_classes
                )
                meeting.participants.add(request.user)
                
                # Add allowed teams
                if restrict_to_classes and selected_class_ids:
                    for class_id in selected_class_ids:
                        try:
                            user_class = UserClass.objects.get(id=class_id)
                            meeting.allowed_classes.add(user_class)
                        except UserClass.DoesNotExist:
                            pass
                
                messages.success(request, f'Meeting "{title}" scheduled successfully!')
                return redirect('calendar')
                
            except Exception as e:
                messages.error(request, f'Error scheduling meeting: {str(e)}')
                return redirect('calendar')
    
    # GET - Display calendar
    # Get upcoming meetings for the user
    meetings = Meeting.objects.filter(
        participants=request.user,
        scheduled_time__gte=timezone.now()
    ).order_by('scheduled_time').select_related('room')
    
    # Group meetings by date for calendar display (simplified - just title and time)
    meetings_by_date = defaultdict(list)
    
    # Group meetings with full data (including ID for deletion)
    meetings_data = defaultdict(list)
    
    for meeting in meetings:
        date_str = meeting.scheduled_time.strftime('%Y-%m-%d')
        time_str = meeting.scheduled_time.strftime('%H:%M')
        
        # Simplified for calendar grid display
        meetings_by_date[date_str].append({
            'title': meeting.title,
            'time': time_str,
        })
        
        # Full data for sidebar (includes ID)
        meetings_data[date_str].append({
            'id': meeting.id,
            'title': meeting.title,
            'time': time_str,
        })
    
    # Convert to JSON for JavaScript
    meetings_json = json.dumps(dict(meetings_by_date))
    meetings_data_json = json.dumps(dict(meetings_data))
    
    context = {
        'meetings': meetings,
        'meetings_json': meetings_json,
        'meetings_data': meetings_data_json,
        'user_classes': user_classes,
        'now': timezone.now(),
    }
    return render(request, 'calendar.html', context)
@login_required
def contacts_view(request):
    """View and manage contacts"""
    if request.method == 'POST':
        contact_username = request.POST.get('contact_username')
        
        try:
            contact_user = User.objects.get(username=contact_username)
            
            if contact_user == request.user:
                messages.error(request, 'You cannot add yourself as a contact')
            elif Contact.objects.filter(user=request.user, contact_user=contact_user).exists():
                messages.warning(request, 'Contact already added')
            else:
                Contact.objects.create(user=request.user, contact_user=contact_user)
                messages.success(request, f'Added {contact_username} to contacts')
        except User.DoesNotExist:
            messages.error(request, 'User not found')
        
        return redirect('contacts')
    
    contacts = Contact.objects.filter(user=request.user).select_related('contact_user')
    
    context = {
        'contacts': contacts,
    }
    return render(request, 'contacts.html', context)

@login_required
def instant_room(request):
    """Create an instant meeting room"""
    room = Room.objects.create(
        name=f"Instant Meeting - {request.user.username}",
        host=request.user,
        room_type='public'
    )

    _create_meeting(
        room=room, 
        host=request.user, 
        title=f"Instant - {request.user.username}", 
        scheduled_time=timezone.now()
    )

    return redirect('room_detail', room_id=room.id)

@login_required
def webrtc_video_room(request, room_id):
    """WebRTC Video Room"""
    try:
        room = MeetingRoom.objects.get(id=room_id)
    except MeetingRoom.DoesNotExist:
        try:
            room = Room.objects.get(id=room_id)
            meeting_room, created = MeetingRoom.objects.get_or_create(
                id=room_id,
                defaults={
                    'name': room.name,
                    'host': room.host,
                }
            )
            room = meeting_room
        except:
            room = MeetingRoom.objects.create(
                id=room_id,
                name=f"Video Room - {room_id}",
                host=request.user
            )
    
    # Add user to participants
    if request.user not in room.participants.all():
        room.participants.add(request.user)
    
    return render(request, 'video_room.html', {
        'room': room,
        'user': request.user
    })
# ===== CLASS MANAGEMENT VIEWS =====
@login_required
def manage_classes(request):
    """View for managing user classes"""
    # FIX: Correct Q object usage
    user_classes = UserClass.objects.filter(
        Q(created_by=request.user) | 
        Q(members__user=request.user)
    ).distinct()
    
    # Classes user is a member of
    my_classes = UserClass.objects.filter(members__user=request.user)
    
    # Classes user created
    created_classes = UserClass.objects.filter(created_by=request.user)
    
    context = {
        'user_classes': user_classes,
        'my_classes': my_classes,
        'created_classes': created_classes,
    }
    return render(request, 'manage_classes.html', context)


# views.py - UPDATE ONLY THESE FUNCTIONS (keep everything else the same)
# Just change user-facing messages to say "team" instead of "class"

@login_required
def create_class(request):
    """Create a new team/department"""
    if request.method == 'POST':
        name = request.POST.get('name')
        code = request.POST.get('code')
        description = request.POST.get('description', '')
        
        if not name or not code:
            messages.error(request, 'Team name and code are required')
            return redirect('create_class')
        
        try:
            # Create the team
            user_class = UserClass.objects.create(
                name=name,
                code=code.upper(),
                description=description,
                created_by=request.user
            )
            
            # Add creator as team manager
            ClassMembership.objects.create(
                user=request.user,
                user_class=user_class,
                role='teacher'  # Keep database value, just change UI display
            )
            
            messages.success(request, f'Team "{name}" created successfully!')
            return redirect('manage_classes')
            
        except IntegrityError:
            messages.error(request, 'Team code already exists')
            return redirect('create_class')
    
    return render(request, 'create_class.html')


@login_required
def join_class(request):
    """Join a team using code"""
    if request.method == 'POST':
        class_code = request.POST.get('class_code', '').upper().strip()
        
        try:
            user_class = UserClass.objects.get(code=class_code, is_active=True)
            
            # Check if already a member
            if ClassMembership.objects.filter(user=request.user, user_class=user_class).exists():
                messages.warning(request, f'You are already a member of {user_class.name}')
            else:
                # Join the team
                ClassMembership.objects.create(
                    user=request.user,
                    user_class=user_class,
                    role='student'  # Keep database value, just change UI display
                )
                messages.success(request, f'Successfully joined {user_class.name}!')
            
            return redirect('manage_classes')
            
        except UserClass.DoesNotExist:
            messages.error(request, 'Team not found or is inactive')
            return redirect('manage_classes')
    
    return redirect('manage_classes')


@login_required
def class_detail(request, class_id):
    """View team details and members"""
    user_class = get_object_or_404(UserClass, id=class_id)
    
    # Check if user is a member
    is_member = ClassMembership.objects.filter(
        user=request.user, 
        user_class=user_class
    ).exists()
    
    # Check if user has permission to view
    if not is_member and user_class.created_by != request.user:
        messages.error(request, 'You do not have permission to view this team')
        return redirect('manage_classes')
    
    members = ClassMembership.objects.filter(user_class=user_class).select_related('user')
    meetings = Meeting.objects.filter(allowed_classes=user_class).order_by('-scheduled_time')[:10]
    
    context = {
        'user_class': user_class,
        'is_member': is_member,
        'members': members,
        'meetings': meetings,
    }
    return render(request, 'class_detail.html', context)
@login_required
def session_dashboard(request):
    """Dashboard showing user's session history"""
    
    # User's active sessions
    active_sessions = UserSession.objects.filter(
        user=request.user,
        is_active=True
    ).order_by('-last_activity')
    
    # Recent sessions (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    recent_sessions = UserSession.objects.filter(
        user=request.user,
        login_time__gte=thirty_days_ago
    ).order_by('-login_time')[:20]
    
    # Meeting sessions
    recent_meetings = MeetingSession.objects.filter(
        user=request.user
    ).select_related('meeting', 'room').order_by('-joined_at')[:10]
    
    # Activity log
    recent_activities = UserActivity.objects.filter(
        user=request.user
    ).order_by('-timestamp')[:20]
    
    # Statistics
    total_sessions = UserSession.objects.filter(user=request.user).count()
    total_meeting_time = MeetingSession.objects.filter(
        user=request.user,
        left_at__isnull=False
    ).aggregate(
        total=Sum('video_enabled_duration')
    )['total'] or 0
    
    context = {
        'active_sessions': active_sessions,
        'recent_sessions': recent_sessions,
        'recent_meetings': recent_meetings,
        'recent_activities': recent_activities,
        'total_sessions': total_sessions,
        'total_meeting_time': total_meeting_time // 60,  # Convert to minutes
    }
    
    return render(request, 'session_dashboard.html', context)


@login_required
def terminate_session(request, session_id):
    """Terminate a specific session"""
    if request.method == 'POST':
        try:
            session = UserSession.objects.get(
                id=session_id,
                user=request.user
            )
            session.is_active = False
            session.logout_time = timezone.now()
            session.save()
            
            messages.success(request, 'Session terminated successfully')
        except UserSession.DoesNotExist:
            messages.error(request, 'Session not found')
    
    return redirect('session_dashboard')


@login_required
def online_users_api(request):
    """API endpoint to get currently online users"""
    online_users = OnlineUser.get_online_users()
    
    data = {
        'count': online_users.count(),
        'users': [
            {
                'username': user.user.username,
                'last_seen': user.last_seen.isoformat(),
                'is_in_meeting': user.is_in_meeting,
                'current_page': user.current_page
            }
            for user in online_users
        ]
    }
    
    return JsonResponse(data)


@login_required
def user_analytics(request):
    """Analytics dashboard for user activity"""
    
    # Get date range
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    # Sessions by day
    sessions_by_day = UserSession.objects.filter(
        user=request.user,
        login_time__gte=thirty_days_ago
    ).extra(
        select={'day': 'date(login_time)'}
    ).values('day').annotate(
        count=Count('id')
    ).order_by('day')
    
    # Activity breakdown
    activity_breakdown = UserActivity.objects.filter(
        user=request.user,
        timestamp__gte=thirty_days_ago
    ).values('activity_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Device usage
    device_usage = UserSession.objects.filter(
        user=request.user,
        login_time__gte=thirty_days_ago
    ).values('device_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Browser usage
    browser_usage = UserSession.objects.filter(
        user=request.user,
        login_time__gte=thirty_days_ago
    ).values('browser').annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    # Meeting statistics
    meeting_stats = MeetingSession.objects.filter(
        user=request.user,
        joined_at__gte=thirty_days_ago
    ).aggregate(
        total_meetings=Count('id'),
        total_duration=Sum('video_enabled_duration'),
        avg_duration=Avg('video_enabled_duration')
    )
    
    context = {
        'sessions_by_day': list(sessions_by_day),
        'activity_breakdown': list(activity_breakdown),
        'device_usage': list(device_usage),
        'browser_usage': list(browser_usage),
        'meeting_stats': meeting_stats,
    }
    
    return render(request, 'user_analytics.html', context)


# Helper function to track meeting join/leave
def track_meeting_session(user, meeting, action='join'):
    """Track when users join/leave meetings"""
    
    if action == 'join':
        # Create meeting session
        session = MeetingSession.objects.create(
            user=user,
            meeting=meeting,
            room=meeting.room,
            device_type=get_device_type(),  # You'd get this from request
            browser=get_browser()  # You'd get this from request
        )
        
        # Update online status
        OnlineUser.objects.update_or_create(
            user=user,
            defaults={
                'is_in_meeting': True,
                'current_meeting': meeting
            }
        )
        
        # Log activity
        UserActivity.objects.create(
            user=user,
            activity_type='meeting_joined',
            description=f"Joined meeting: {meeting.title}",
            meeting=meeting,
            room=meeting.room
        )
        
    elif action == 'leave':
        # Close meeting session
        session = MeetingSession.objects.filter(
            user=user,
            meeting=meeting,
            left_at__isnull=True
        ).first()
        
        if session:
            session.left_at = timezone.now()
            session.save()
        
        # Update online status
        OnlineUser.objects.filter(user=user).update(
            is_in_meeting=False,
            current_meeting=None
        )
        
        # Log activity
        UserActivity.objects.create(
            user=user,
            activity_type='meeting_left',
            description=f"Left meeting: {meeting.title}",
            meeting=meeting,
            room=meeting.room
        )


# Signal handlers for automatic session tracking
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

@receiver(user_logged_in)
def on_user_login(sender, request, user, **kwargs):
    """Track user login"""
    UserActivity.objects.create(
        user=user,
        activity_type='login',
        description='User logged in',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')
    )


@receiver(user_logged_out)
def on_user_logout(sender, request, user, **kwargs):
    """Track user logout"""
    
    # Mark session as inactive
    if hasattr(request, 'session') and request.session.session_key:
        UserSession.objects.filter(
            user=user,
            session_key=request.session.session_key,
            is_active=True
        ).update(
            is_active=False,
            logout_time=timezone.now()
        )
    
    # Log activity
    UserActivity.objects.create(
        user=user,
        activity_type='logout',
        description='User logged out',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')
    )


def get_client_ip(request):
    """Helper to get IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@login_required
def video_room(request, room_id):
    """
    WebRTC Video Call Room
    """
    try:
        # Try to get room
        room = Room.objects.get(id=room_id)
        
        # Get or create meeting for this room
        meeting, created = Meeting.objects.get_or_create(
            room=room,
            defaults={
                'title': room.name,
                'scheduled_time': timezone.now(),
                'duration': 60
            }
        )
        
    except Room.DoesNotExist:
        # Room doesn't exist, create it
        room = Room.objects.create(
            id=room_id,
            name=f"Meeting Room - {room_id}",
            host=request.user
        )
        meeting = Meeting.objects.create(
            room=room,
            title=room.name,
            scheduled_time=timezone.now(),
            duration=60
        )
    
    # Add user as participant
    meeting.participants.add(request.user)
    
    # Create meeting session
    MeetingSession.objects.get_or_create(
        user=request.user,
        meeting=meeting,
        room=room,
        defaults={
            'joined_at': timezone.now()
        }
    )
    
    # Get all participants
    participants = meeting.participants.all()
    
    context = {
        'room': room,
        'meeting': meeting,
        'room_id': str(room_id),
        'user': request.user,
        'participants': participants,
        'is_host': room.host == request.user,
    }
    
    return render(request, 'video_room.html', context)


@login_required
def leave_meeting(request, room_id):
    """Handle leaving a meeting"""
    try:
        room = Room.objects.get(id=room_id)
        meeting = Meeting.objects.filter(room=room).first()
        
        if meeting:
            # Update meeting session
            session = MeetingSession.objects.filter(
                user=request.user,
                meeting=meeting,
                left_at__isnull=True
            ).first()
            
            if session:
                session.left_at = timezone.now()
                session.save()
            
            # Remove from participants
            meeting.participants.remove(request.user)
    except:
        pass
    
    return redirect('home')




