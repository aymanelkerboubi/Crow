# crow_app/admin_views.py - COMPLETE FIXED VERSION

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q, F
from datetime import timedelta, datetime
from .models import (
    AdminRole, UserSession, MeetingSession, UserActivity, 
    OnlineUser, Meeting, UserClass, ClassMembership, Contact,
    SiteStatistics
)
from django.contrib import messages

from django.db import IntegrityError


def is_admin(user):
    """Check if user has admin role"""
    try:
        return hasattr(user, 'admin_role') and user.admin_role is not None
    except:
        return False


@login_required
def admin_dashboard(request):
    """Main admin dashboard with comprehensive statistics"""
    
    # Check if user is admin
    if not is_admin(request.user):
        messages.error(request, "You don't have admin access")
        return redirect('home')
    
    admin_role = request.user.admin_role
    
    # Time ranges
    today = timezone.now().date()
    thirty_days_ago = today - timedelta(days=30)
    seven_days_ago = today - timedelta(days=7)
    
    # === OVERVIEW STATISTICS ===
    
    # Total counts
    total_users = User.objects.count()
    total_teams = UserClass.objects.count()
    total_meetings = Meeting.objects.count()
    total_contacts = Contact.objects.count()
    
    # Active users (logged in last 30 days)
    active_users_30d = UserSession.objects.filter(
        login_time__gte=thirty_days_ago
    ).values('user').distinct().count()
    
    # Online users (active in last 2 minutes)
    online_now = OnlineUser.get_online_count()
    
    # New users (last 7 days)
    new_users_7d = User.objects.filter(
        date_joined__gte=seven_days_ago
    ).count()
    
    # Meetings today
    meetings_today = Meeting.objects.filter(
        created_at__date=today
    ).count()
    
    # === USER ANALYTICS ===
    
    # Most active users (by session count) - FIXED
    most_active_users = User.objects.annotate(
        session_count=Count('sessions', filter=Q(sessions__login_time__gte=thirty_days_ago)),
        total_meeting_time=Sum('meeting_sessions__video_enabled_duration')
    ).filter(
        session_count__gt=0
    ).order_by('-session_count')[:10]
    
    # Users online in meetings
    users_in_meetings = OnlineUser.objects.filter(
        is_in_meeting=True
    ).select_related('user', 'current_meeting')
    
    # === TEAM ANALYTICS - FIXED ===
    
    # Most active teams (by member count only)
    most_active_teams = UserClass.objects.annotate(
        member_count=Count('members')
    ).filter(
        is_active=True
    ).order_by('-member_count')[:10]
    
    # Team growth (new teams per day - last 7 days)
    team_growth = UserClass.objects.filter(
        created_at__gte=seven_days_ago
    ).extra(
        select={'day': 'date(created_at)'}
    ).values('day').annotate(
        count=Count('id')
    ).order_by('day')
    
    # === MEETING ANALYTICS ===
    
    # Total meeting time (last 30 days)
    meeting_stats = MeetingSession.objects.filter(
        joined_at__gte=thirty_days_ago,
        left_at__isnull=False
    ).aggregate(
        total_sessions=Count('id'),
        total_time=Sum('video_enabled_duration'),
        avg_duration=Avg('video_enabled_duration'),
        total_video_time=Sum('video_enabled_duration'),
        total_screen_share_time=Sum('screen_shared_duration')
    )
    
    # Convert seconds to minutes
    meeting_stats['total_time_minutes'] = (meeting_stats['total_time'] or 0) // 60
    meeting_stats['avg_duration_minutes'] = (meeting_stats['avg_duration'] or 0) // 60
    
    # Meetings per day (last 30 days)
    meetings_per_day = Meeting.objects.filter(
        created_at__gte=thirty_days_ago
    ).extra(
        select={'day': 'date(created_at)'}
    ).values('day').annotate(
        count=Count('id')
    ).order_by('day')
    
    # Top meeting hosts - FIXED
    top_hosts = User.objects.annotate(
        hosted_count=Count('hosted_rooms')
    ).filter(
        hosted_count__gt=0
    ).order_by('-hosted_count')[:10]
    
    # === ACTIVITY ANALYTICS ===
    
    # Activity breakdown (last 30 days)
    activity_breakdown = UserActivity.objects.filter(
        timestamp__gte=thirty_days_ago
    ).values('activity_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Login activity per day
    logins_per_day = UserActivity.objects.filter(
        activity_type='login',
        timestamp__gte=thirty_days_ago
    ).extra(
        select={'day': 'date(timestamp)'}
    ).values('day').annotate(
        count=Count('id')
    ).order_by('day')
    
    # === DEVICE & BROWSER STATS ===
    
    device_stats = UserSession.objects.filter(
        login_time__gte=thirty_days_ago
    ).values('device_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    browser_stats = UserSession.objects.filter(
        login_time__gte=thirty_days_ago
    ).values('browser').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # === RECENT ACTIVITY ===
    
    recent_activities = UserActivity.objects.select_related(
        'user', 'meeting', 'room', 'team'
    ).order_by('-timestamp')[:20]
    
    # Generate today's stats snapshot
    try:
        SiteStatistics.generate_today_stats()
    except Exception as e:
        print(f"Failed to generate stats: {e}")
    
    # Get historical stats for trends
    historical_stats = SiteStatistics.objects.filter(
        date__gte=thirty_days_ago
    ).order_by('date')
    
    context = {
        'admin_role': admin_role,
        
        # Overview
        'total_users': total_users,
        'total_teams': total_teams,
        'total_meetings': total_meetings,
        'total_contacts': total_contacts,
        'active_users_30d': active_users_30d,
        'online_now': online_now,
        'new_users_7d': new_users_7d,
        'meetings_today': meetings_today,
        
        # Users
        'most_active_users': most_active_users,
        'users_in_meetings': users_in_meetings,
        
        # Teams
        'most_active_teams': most_active_teams,
        'team_growth': list(team_growth),
        
        # Meetings
        'meeting_stats': meeting_stats,
        'meetings_per_day': list(meetings_per_day),
        'top_hosts': top_hosts,
        
        # Activity
        'activity_breakdown': list(activity_breakdown),
        'logins_per_day': list(logins_per_day),
        
        # Device/Browser
        'device_stats': list(device_stats),
        'browser_stats': list(browser_stats),
        
        # Recent
        'recent_activities': recent_activities,
        
        # Historical
        'historical_stats': historical_stats,
    }
    
    return render(request, 'admin/dashboard.html', context)


@login_required
def admin_users_list(request):
    """List all users with management options"""
    if not is_admin(request.user):
        messages.error(request, "Access denied")
        return redirect('home')
    
    # Get all users with annotations - FIXED
    users = User.objects.annotate(
        session_count=Count('sessions'),
        meeting_count=Count('meeting_sessions'),
        team_count=Count('class_memberships')
    ).order_by('-date_joined')
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(users, 50)
    page_number = request.GET.get('page')
    users_page = paginator.get_page(page_number)
    
    context = {
        'users': users_page,
        'total_users': users.count(),
    }
    
    return render(request, 'admin/users_list.html', context)


@login_required
def admin_user_detail(request, user_id):
    """Detailed view of a specific user"""
    if not is_admin(request.user):
        messages.error(request, "Access denied")
        return redirect('home')
    
    user = get_object_or_404(User, id=user_id)
    
    # User statistics
    user_stats = {
        'total_sessions': UserSession.objects.filter(user=user).count(),
        'total_meetings': MeetingSession.objects.filter(user=user).count(),
        'total_teams': ClassMembership.objects.filter(user=user).count(),
        'total_contacts': Contact.objects.filter(user=user).count(),
        'total_activities': UserActivity.objects.filter(user=user).count(),
    }
    
    # Recent sessions
    recent_sessions = UserSession.objects.filter(user=user).order_by('-login_time')[:10]
    
    # Recent meetings
    recent_meetings = MeetingSession.objects.filter(
        user=user
    ).select_related('meeting', 'room').order_by('-joined_at')[:10]
    
    # Recent activities
    recent_activities = UserActivity.objects.filter(
        user=user
    ).order_by('-timestamp')[:20]
    
    context = {
        'viewed_user': user,
        'user_stats': user_stats,
        'recent_sessions': recent_sessions,
        'recent_meetings': recent_meetings,
        'recent_activities': recent_activities,
    }
    
    return render(request, 'admin/user_detail.html', context)


@login_required
def admin_teams_list(request):
    """List all teams with statistics - FIXED"""
    if not is_admin(request.user):
        messages.error(request, "Access denied")
        return redirect('home')
    
    teams = UserClass.objects.annotate(
        member_count=Count('members')
    ).order_by('-created_at')
    
    context = {
        'teams': teams,
        'total_teams': teams.count(),
    }
    
    return render(request, 'admin/teams_list.html', context)


@login_required
def admin_meetings_list(request):
    """List all meetings with statistics - FIXED"""
    if not is_admin(request.user):
        messages.error(request, "Access denied")
        return redirect('home')
    
    meetings = Meeting.objects.select_related(
        'room__host'
    ).order_by('-created_at')
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(meetings, 50)
    page_number = request.GET.get('page')
    meetings_page = paginator.get_page(page_number)
    
    context = {
        'meetings': meetings_page,
        'total_meetings': meetings.count(),
    }
    
    return render(request, 'admin/meetings_list.html', context)


@login_required
def admin_analytics_api(request):
    """API endpoint for chart data"""
    if not is_admin(request.user):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    chart_type = request.GET.get('type', 'users')
    days = int(request.GET.get('days', 30))
    
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)
    
    if chart_type == 'users':
        # User signups over time
        data = User.objects.filter(
            date_joined__date__gte=start_date
        ).extra(
            select={'day': 'date(date_joined)'}
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')
        
    elif chart_type == 'meetings':
        # Meetings created over time
        data = Meeting.objects.filter(
            created_at__gte=start_date
        ).extra(
            select={'day': 'date(created_at)'}
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')
        
    elif chart_type == 'logins':
        # Logins over time
        data = UserActivity.objects.filter(
            activity_type='login',
            timestamp__gte=start_date
        ).extra(
            select={'day': 'date(timestamp)'}
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')
    
    else:
        return JsonResponse({'error': 'Invalid chart type'}, status=400)
    
    return JsonResponse({
        'data': list(data),
        'chart_type': chart_type,
        'days': days
    })


@login_required  
def make_admin(request, user_id):
    """Make a user an admin (super_admin only)"""
    if not is_admin(request.user):
        messages.error(request, "Access denied")
        return redirect('home')
    
    if not request.user.admin_role.can_manage_admins:
        messages.error(request, "You don't have permission to manage admins")
        return redirect('admin_dashboard')
    
    if request.method == 'POST':
        user = get_object_or_404(User, id=user_id)
        role = request.POST.get('role', 'moderator')
        
        AdminRole.objects.update_or_create(
            user=user,
            defaults={'role': role}
        )
        
        messages.success(request, f"{user.username} is now an admin with role: {role}")
        return redirect('admin_users_list')
    
    return redirect('admin_dashboard')
@login_required
def admin_manage_users(request):
    """
    User management page - add, edit, delete users
    Super admin only
    """
    if not is_admin(request.user):
        messages.error(request, "Access denied")
        return redirect('home')
    
    if not request.user.admin_role.can_manage_users:
        messages.error(request, "You don't have permission to manage users")
        return redirect('admin_dashboard')
    
    # Get all users with their roles
    users = User.objects.annotate(
        session_count=Count('sessions'),
        meeting_count=Count('meeting_sessions'),
        team_count=Count('class_memberships')
    ).select_related('admin_role').order_by('-date_joined')
    
    # Get available admin roles
    admin_roles = AdminRole.ROLE_CHOICES
    
    context = {
        'users': users,
        'admin_roles': admin_roles,
        'can_manage_admins': request.user.admin_role.can_manage_admins,
    }
    
    return render(request, 'admin/manage_users.html', context)


@login_required
def admin_create_user(request):
    """Create a new user"""
    if not is_admin(request.user):
        messages.error(request, "Access denied")
        return redirect('home')
    
    if not request.user.admin_role.can_manage_users:
        messages.error(request, "You don't have permission to create users")
        return redirect('admin_dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        is_admin_user = request.POST.get('is_admin', 'no') == 'yes'
        admin_role = request.POST.get('admin_role', 'moderator')
        
        # Validation
        if not username or not email or not password:
            messages.error(request, "Username, email, and password are required")
            return redirect('admin_manage_users')
        
        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters")
            return redirect('admin_manage_users')
        
        try:
            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name
            )
            
            # Create admin role if requested
            if is_admin_user and request.user.admin_role.can_manage_admins:
                AdminRole.objects.create(
                    user=user,
                    role=admin_role
                )
            
            # Log activity
            UserActivity.objects.create(
                user=request.user,
                activity_type='user_created',
                description=f"Created user: {username}"
            )
            
            messages.success(request, f"User {username} created successfully")
            return redirect('admin_manage_users')
            
        except IntegrityError:
            messages.error(request, f"Username '{username}' already exists")
            return redirect('admin_manage_users')
        except Exception as e:
            messages.error(request, f"Error creating user: {str(e)}")
            return redirect('admin_manage_users')
    
    return redirect('admin_manage_users')


@login_required
def admin_edit_user(request, user_id):
    """Edit an existing user"""
    if not is_admin(request.user):
        messages.error(request, "Access denied")
        return redirect('home')
    
    if not request.user.admin_role.can_manage_users:
        messages.error(request, "You don't have permission to edit users")
        return redirect('admin_dashboard')
    
    user = get_object_or_404(User, id=user_id)
    
    # Prevent editing self
    if user.id == request.user.id:
        messages.error(request, "You cannot edit your own account from this page")
        return redirect('admin_manage_users')
    
    if request.method == 'POST':
        # Update basic info
        user.email = request.POST.get('email', user.email).strip()
        user.first_name = request.POST.get('first_name', user.first_name).strip()
        user.last_name = request.POST.get('last_name', user.last_name).strip()
        user.is_active = request.POST.get('is_active', 'no') == 'yes'
        
        # Update password if provided
        new_password = request.POST.get('new_password', '').strip()
        if new_password:
            if len(new_password) >= 6:
                user.set_password(new_password)
            else:
                messages.error(request, "Password must be at least 6 characters")
                return redirect('admin_manage_users')
        
        try:
            user.save()
            
            # Update admin role if user has permission
            if request.user.admin_role.can_manage_admins:
                is_admin_user = request.POST.get('is_admin', 'no') == 'yes'
                admin_role = request.POST.get('admin_role', 'moderator')
                
                if is_admin_user:
                    # Create or update admin role
                    AdminRole.objects.update_or_create(
                        user=user,
                        defaults={'role': admin_role}
                    )
                else:
                    # Remove admin role if exists
                    if hasattr(user, 'admin_role'):
                        user.admin_role.delete()
            
            # Log activity
            UserActivity.objects.create(
                user=request.user,
                activity_type='user_updated',
                description=f"Updated user: {user.username}"
            )
            
            messages.success(request, f"User {user.username} updated successfully")
            
        except Exception as e:
            messages.error(request, f"Error updating user: {str(e)}")
        
        return redirect('admin_manage_users')
    
    # GET request - show edit modal data via API
    return redirect('admin_manage_users')


@login_required
def admin_delete_user(request, user_id):
    """Delete a user"""
    if not is_admin(request.user):
        messages.error(request, "Access denied")
        return redirect('home')
    
    if not request.user.admin_role.can_delete_content:
        messages.error(request, "You don't have permission to delete users")
        return redirect('admin_dashboard')
    
    user = get_object_or_404(User, id=user_id)
    
    # Prevent deleting self
    if user.id == request.user.id:
        messages.error(request, "You cannot delete your own account")
        return redirect('admin_manage_users')
    
    # Prevent deleting superusers (safety)
    if user.is_superuser:
        messages.error(request, "Cannot delete superuser accounts")
        return redirect('admin_manage_users')
    
    if request.method == 'POST':
        username = user.username
        
        try:
            # Log activity before deletion
            UserActivity.objects.create(
                user=request.user,
                activity_type='user_deleted',
                description=f"Deleted user: {username}"
            )
            
            # Delete user
            user.delete()
            
            messages.success(request, f"User {username} deleted successfully")
            
        except Exception as e:
            messages.error(request, f"Error deleting user: {str(e)}")
    
    return redirect('admin_manage_users')


@login_required
def admin_toggle_user_status(request, user_id):
    """Toggle user active/inactive status"""
    if not is_admin(request.user):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    if not request.user.admin_role.can_manage_users:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    user = get_object_or_404(User, id=user_id)
    
    # Prevent toggling self
    if user.id == request.user.id:
        return JsonResponse({'error': 'Cannot modify own account'}, status=400)
    
    # Toggle status
    user.is_active = not user.is_active
    user.save()
    
    # Log activity
    UserActivity.objects.create(
        user=request.user,
        activity_type='user_status_changed',
        description=f"{'Activated' if user.is_active else 'Deactivated'} user: {user.username}"
    )
    
    return JsonResponse({
        'success': True,
        'is_active': user.is_active,
        'message': f"User {user.username} {'activated' if user.is_active else 'deactivated'}"
    })


@login_required
def admin_get_user_data(request, user_id):
    """Get user data for editing (API endpoint)"""
    if not is_admin(request.user):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    user = get_object_or_404(User, id=user_id)
    
    data = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_active': user.is_active,
        'is_admin': hasattr(user, 'admin_role'),
        'admin_role': user.admin_role.role if hasattr(user, 'admin_role') else None,
        'date_joined': user.date_joined.isoformat(),
    }
    
    return JsonResponse(data)


@login_required
def admin_bulk_action(request):
    """Perform bulk actions on users"""
    if not is_admin(request.user):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    if not request.user.admin_role.can_manage_users:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        
        action = data.get('action')
        user_ids = data.get('user_ids', [])
        
        if not user_ids:
            return JsonResponse({'error': 'No users selected'}, status=400)
        
        # Exclude self from bulk actions
        user_ids = [uid for uid in user_ids if uid != request.user.id]
        
        try:
            if action == 'activate':
                User.objects.filter(id__in=user_ids).update(is_active=True)
                message = f"Activated {len(user_ids)} users"
                
            elif action == 'deactivate':
                User.objects.filter(id__in=user_ids).update(is_active=False)
                message = f"Deactivated {len(user_ids)} users"
                
            elif action == 'delete' and request.user.admin_role.can_delete_content:
                # Don't delete superusers
                users_to_delete = User.objects.filter(
                    id__in=user_ids,
                    is_superuser=False
                )
                count = users_to_delete.count()
                users_to_delete.delete()
                message = f"Deleted {count} users"
            else:
                return JsonResponse({'error': 'Invalid action'}, status=400)
            
            # Log activity
            UserActivity.objects.create(
                user=request.user,
                activity_type='bulk_action',
                description=f"Bulk action: {action} on {len(user_ids)} users"
            )
            
            return JsonResponse({'success': True, 'message': message})
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Invalid request'}, status=400)