from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.notifications.tasks import push_notification_task

from .models import IoTEvent


EVENT_MESSAGES = {
    'OTP_VALIDATED': 'Kode OTP berhasil diverifikasi oleh perangkat.',
    'TAMPER_DETECTED': 'Sensor mendeteksi getaran pada locker.',
    'PARCEL_DETECTED': 'Paket baru terdeteksi di locker inbound.',
    'TRAPDOOR_OPENED': 'Trapdoor locker terbuka.',
    'TRAPDOOR_CLOSED': 'Trapdoor locker tertutup.',
    'RFID_ACCEPTED': 'RFID valid – akses diberikan.',
    'RFID_DENIED': 'RFID tidak valid – akses ditolak.',
    'LOCKER_OPENED': 'Locker dibuka melalui panel front-end.',
    'LOCKER_ACCESS_GRANTED': 'OTP valid – locker dibuka.',
    'LOCKER_ACCESS_DENIED': 'Percobaan OTP gagal.',
}

OWNER_BROADCAST_EVENTS = {'LOCKER_DOOR_CLOSED', 'LOCKER_PACKAGE_DETECTED', 'TAMPER_DETECTED'}


def _locker_label(payload: dict) -> str:
    locker = payload.get('locker_number') or payload.get('locker') or payload.get('locker_id')
    return locker or '?'


def _resolve_message(event_key: str, payload: dict) -> str | None:
    if event_key == 'LOCKER_OPENED':
        locker = _locker_label(payload)
        owner_username = payload.get('owner_username')
        if owner_username:
            return f"Locker {locker} dibuka by app oleh owner {owner_username}"
        return f"Locker {locker} dibuka by app"
    if event_key == 'TAMPER_DETECTED':
        return "Sensor mendeteksi getaran"
    if event_key == 'LOCKER_DOOR_CLOSED':
        return f"Pintu loker {_locker_label(payload)} sudah tertutup."
    if event_key == 'LOCKER_PACKAGE_DETECTED':
        return f"Paket terdeteksi di loker {_locker_label(payload)}."
    return EVENT_MESSAGES.get(event_key)


@receiver(post_save, sender=IoTEvent)
def notify_priority_events(sender, instance: IoTEvent, created: bool, **kwargs) -> None:
    if not created:
        return

    payload = instance.payload or {}
    if instance.user_id and not payload.get('user_id'):
        payload['user_id'] = instance.user_id
    event_key = (payload.get('event') or instance.event_type or '').upper()
    message = None

    # Deteksi anomali getaran: 7 event terakhir semuanya tamper
    if event_key == 'TAMPER_DETECTED':
        last_payloads = list(
            IoTEvent.objects.order_by('-created_at').values_list('payload', flat=True)[:7]
        )
        if len(last_payloads) == 7 and all(
            (p or {}).get('event', '').upper() == 'TAMPER_DETECTED' for p in last_payloads
        ):
            message = "WARNING!! SENSOR MENDETEKSI ANOMALI GETARAN"

    if not message:
        message = _resolve_message(event_key, payload)

    if not message:
        return

    target_ids = []
    User = get_user_model()
    if event_key in OWNER_BROADCAST_EVENTS:
        target_ids = list(
            User.objects.filter(role=User.Role.OWNER).values_list('id', flat=True)
        )

    if instance.user_id:
        target_ids.append(instance.user_id)
    if not target_ids:
        target_ids = list(User.objects.filter(is_superuser=True).values_list('id', flat=True))

    push_notification_task(
        user_ids=target_ids,
        title='SmartLocker Event',
        body=message,
    )
