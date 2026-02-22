from django.contrib import admin
from .models import ClassMembership, Room, Meeting, MeetingParticipant, Contact, UserClass, UserProfile


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
	list_display = ('name', 'host', 'room_type', 'is_active', 'created_at')
	list_filter = ('room_type', 'is_active')


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
	list_display = ('title', 'room', 'scheduled_time', 'duration', 'created_at')
	list_filter = ('scheduled_time',)


@admin.register(MeetingParticipant)
class MeetingParticipantAdmin(admin.ModelAdmin):
	list_display = ('user', 'meeting', 'joined_at', 'left_at')


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
	list_display = ('user', 'contact_user', 'added_at')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
	list_display = ('user', 'phone_number', 'company', 'job_title')
@admin.register(UserClass)
class UserClassAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'created_by', 'created_at', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'description')

@admin.register(ClassMembership)
class ClassMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_class', 'role', 'date_joined')
    list_filter = ('role', 'user_class')