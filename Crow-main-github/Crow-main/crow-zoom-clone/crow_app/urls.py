from django.urls import path
from . import views,admin_views 

urlpatterns = [
    # Authentication
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    
    # Profile & Settings
    path('settings/', views.settings_view, name='settings'),
    path('profile/', views.profile_view, name='profile'),
    
    # Rooms & Meetings
    path('create-room/', views.create_room, name='create_room'),
    path('room/<int:room_id>/', views.room_detail, name='room_detail'),
    path('instant-room/', views.instant_room, name='instant_room'),
    path('calendar/', views.calendar_view, name='calendar'),
    path('contacts/', views.contacts_view, name='contacts'),
    
    # Video
    path('video/<uuid:room_id>/', views.webrtc_video_room, name='webrtc_video_room'),
    
    # AI Chatbot
    path('ai-chatbot/', views.ai_chatbot, name='ai_chatbot'),
    path('ai-chat-api/', views.ai_chat_api, name='ai_chat_api'),
    
    # ===== NEW: CLASS MANAGEMENT URLS =====
    path('classes/', views.manage_classes, name='manage_classes'),
    path('classes/create/', views.create_class, name='create_class'),
    path('classes/join/', views.join_class, name='join_class'),
    path('classes/<int:class_id>/', views.class_detail, name='class_detail'),

# Session management
    path('sessions/', views.session_dashboard, name='session_dashboard'),
    path('sessions/terminate/<int:session_id>/', views.terminate_session, name='terminate_session'),
    path('analytics/', views.user_analytics, name='user_analytics'),
    
    # API endpoints
    path('api/online-users/', views.online_users_api, name='online_users_api'),

    # Admin routes
    path('admin-dashboard/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('admin-dashboard/users/', admin_views.admin_users_list, name='admin_users_list'),
    path('admin-dashboard/users/<int:user_id>/', admin_views.admin_user_detail, name='admin_user_detail'),
    path('admin-dashboard/teams/', admin_views.admin_teams_list, name='admin_teams_list'),
    path('admin-dashboard/meetings/', admin_views.admin_meetings_list, name='admin_meetings_list'),
    path('admin-dashboard/analytics-api/', admin_views.admin_analytics_api, name='admin_analytics_api'),
    path('admin-dashboard/make-admin/<int:user_id>/', admin_views.make_admin, name='make_admin'),


    # User Management
    path('admin-dashboard/manage-users/', admin_views.admin_manage_users, name='admin_manage_users'),
    path('admin-dashboard/create-user/', admin_views.admin_create_user, name='admin_create_user'),
    path('admin-dashboard/edit-user/<int:user_id>/', admin_views.admin_edit_user, name='admin_edit_user'),
    path('admin-dashboard/delete-user/<int:user_id>/', admin_views.admin_delete_user, name='admin_delete_user'),
    path('admin-dashboard/toggle-status/<int:user_id>/', admin_views.admin_toggle_user_status, name='admin_toggle_user_status'),
    path('admin-dashboard/get-user/<int:user_id>/', admin_views.admin_get_user_data, name='admin_get_user_data'),
    path('admin-dashboard/bulk-action/', admin_views.admin_bulk_action, name='admin_bulk_action'),

    # Video Calling
    path('video/<int:room_id>/', views.video_room, name='video_room'),
    path('leave-meeting/<int:room_id>/', views.leave_meeting, name='leave_meeting'),
    

]
