from rest_framework import serializers
from django.contrib.auth.models import User
from accounts.models import UserProfile, RoleChoices
from api.v1.utils import format_choice_field


class UserAdminSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(choices=RoleChoices.choices, write_only=True, required=False)
    role_display = serializers.SerializerMethodField(read_only=True)
    mobile = serializers.CharField(max_length=20, required=False, allow_blank=True, write_only=True)
    mobile_display = serializers.CharField(source='profile.mobile', read_only=True)
    personnel_code = serializers.CharField(max_length=30, required=False, allow_blank=True, write_only=True)
    personnel_code_display = serializers.CharField(source='profile.personnel_code', read_only=True)
    password = serializers.CharField(write_only=True, required=False, min_length=4)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email',
            'is_active', 'role', 'role_display',
            'mobile', 'mobile_display',
            'personnel_code', 'personnel_code_display',
            'password', 'date_joined', 'last_login'
        ]
        read_only_fields = ['id', 'date_joined', 'last_login', 'role_display', 'mobile_display', 'personnel_code_display']

    def get_role_display(self, obj):
        profile = getattr(obj, 'profile', None)
        if profile:
            return format_choice_field(profile.role, profile.get_role_display())
        return format_choice_field('super_admin' if obj.is_superuser else 'viewer', 'مدیر ارشد' if obj.is_superuser else 'مشاهده‌گر')

    def create(self, validated_data):
        role = validated_data.pop('role', RoleChoices.WEIGHBRIDGE_OPERATOR)
        mobile = validated_data.pop('mobile', '')
        personnel_code = validated_data.pop('personnel_code', '')
        password = validated_data.pop('password', None)

        user = User.objects.create(**validated_data)
        if password:
            user.set_password(password)
            user.save()

        # Update profile
        profile = getattr(user, 'profile', None)
        if not profile:
            profile = UserProfile.objects.create(user=user)
        profile.role = role
        profile.mobile = mobile
        profile.personnel_code = personnel_code
        profile.save()

        return user

    def update(self, instance, validated_data):
        role = validated_data.pop('role', None)
        mobile = validated_data.pop('mobile', None)
        personnel_code = validated_data.pop('personnel_code', None)
        password = validated_data.pop('password', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)
        instance.save()

        profile = getattr(instance, 'profile', None)
        if profile:
            if role is not None:
                profile.role = role
            if mobile is not None:
                profile.mobile = mobile
            if personnel_code is not None:
                profile.personnel_code = personnel_code
            profile.save()

        return instance


class RoleSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField(required=False)
