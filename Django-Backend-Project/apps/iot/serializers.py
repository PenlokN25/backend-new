from rest_framework import serializers

from .models import IoTEvent


class IoTEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = IoTEvent
        fields = ['id', 'user', 'event_type', 'payload', 'created_at']
        read_only_fields = ['id', 'created_at']


class IoTIngestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=False, allow_null=True)
    event_type = serializers.ChoiceField(choices=IoTEvent.EventType.choices, required=False)
    payload = serializers.JSONField()

    def create(self, validated_data):
        user_id = validated_data.pop('user_id', None)
        user = None
        if user_id is not None:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user = User.objects.filter(id=user_id).first()

        event_type = validated_data.get('event_type') or IoTEvent.EventType.GENERIC
        return IoTEvent.objects.create(
            user=user,
            event_type=event_type,
            payload=validated_data['payload'],
        )


class LockerSensorEventSerializer(serializers.Serializer):
    class LockerEvent(serializers.ChoiceField):
        def __init__(self, **kwargs):
            super().__init__(
                choices=['door_closed', 'package_detected'],
                **kwargs,
            )

        def to_internal_value(self, data):
            value = super().to_internal_value(data)
            return value.upper()

    locker_number = serializers.ChoiceField(choices=['1', '3'])
    event = LockerEvent()
    timestamp = serializers.DateTimeField(required=False)

    def create(self, validated_data):
        locker_number = validated_data['locker_number']
        event = validated_data['event']
        timestamp = validated_data.get('timestamp')

        payload = {
            'event': f'LOCKER_{event}',
            'locker_number': locker_number,
        }
        if timestamp:
            payload['timestamp'] = timestamp.isoformat()

        return IoTEvent.objects.create(
            event_type=IoTEvent.EventType.DEVICE,
            payload=payload,
        )
