from __future__ import absolute_import
from __future__ import print_function

from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction, models
from django.utils import timezone
from zerver.lib.upload import delete_message_image
from zerver.models import (Message, UserMessage, ArchiveMessage, ArchiveUserMessage,
                           Attachment, ArchiveAttachment, Realm)

from typing import Any, List


@transaction.atomic
def move_rows(src_model, fields, raw_query, **kwargs):
    # type: (models.Model, List[models.fields.Field], str, **Any) -> None
    src_db_table = src_model._meta.db_table
    src_fields = ["{}.{}".format(src_db_table, field.column) for field in fields]
    dst_fields = [field.column for field in fields]
    sql_args = {
        'src_fields': ','.join(src_fields),
        'dst_fields': ','.join(dst_fields),
    }
    sql_args.update(kwargs)
    with connection.cursor() as cursor:
        cursor.execute(
            raw_query.format(**sql_args)
        )


def move_expired_messages_to_archive():
    # type: () -> None
    query = """
        INSERT INTO zerver_archivemessage ({dst_fields}, archived_date)
        SELECT {src_fields}, '{archived_date}'
        FROM zerver_message
        INNER JOIN zerver_usermessage ON zerver_message.id = zerver_usermessage.message_id
        INNER JOIN zerver_userprofile ON zerver_usermessage.user_profile_id = zerver_userprofile.id
        INNER JOIN zerver_realm ON zerver_userprofile.realm_id = zerver_realm.id
        WHERE zerver_realm.message_retention_days IS NOT NULL
              AND EXTRACT(DAY FROM (CURRENT_DATE - zerver_message.pub_date)) >= zerver_realm.message_retention_days
              AND zerver_message.id NOT IN (SELECT ID FROM zerver_archivemessage)
        GROUP BY zerver_message.id
    """
    move_rows(Message, Message._meta.fields, query, archived_date=timezone.now())


def move_expired_user_messages_to_archive():
    # type: () -> None
    query = """
        INSERT INTO zerver_archiveusermessage ({dst_fields}, archived_date)
        SELECT {src_fields}, '{archived_date}'
        FROM zerver_usermessage
        INNER JOIN zerver_message ON zerver_message.id = zerver_usermessage.message_id
        INNER JOIN zerver_userprofile ON zerver_usermessage.user_profile_id = zerver_userprofile.id
        INNER JOIN zerver_realm ON zerver_userprofile.realm_id = zerver_realm.id
        WHERE zerver_realm.message_retention_days IS NOT NULL
             AND EXTRACT(DAY FROM (CURRENT_DATE - zerver_message.pub_date)) >= zerver_realm.message_retention_days
             AND zerver_usermessage.id NOT IN (SELECT id FROM zerver_archiveusermessage)
    """
    move_rows(UserMessage, UserMessage._meta.fields, query, archived_date=timezone.now())


def move_expired_attachments_to_archive():
    # type: () -> None
    query = """
       INSERT INTO zerver_archiveattachment ({dst_fields}, archived_date)
       SELECT {src_fields}, '{archived_date}'
       FROM zerver_attachment
       INNER JOIN zerver_attachment_messages
           ON zerver_attachment_messages.attachment_id = zerver_attachment.id
       INNER JOIN zerver_message ON zerver_message.id = zerver_attachment_messages.message_id
       INNER JOIN zerver_usermessage ON zerver_message.id = zerver_usermessage.message_id
       INNER JOIN zerver_userprofile ON zerver_usermessage.user_profile_id = zerver_userprofile.id
       INNER JOIN zerver_realm ON zerver_userprofile.realm_id = zerver_realm.id
       WHERE zerver_realm.message_retention_days IS NOT NULL
            AND EXTRACT(DAY FROM (CURRENT_DATE - zerver_message.pub_date)) >= zerver_realm.message_retention_days
            AND zerver_attachment.id NOT IN (SELECT id FROM zerver_archiveattachment)
       GROUP BY zerver_attachment.id
       """
    move_rows(Attachment, Attachment._meta.fields, query, archived_date=timezone.now())


def move_expired_attachments_message_rows_to_archive():
    # type: () -> None
    query = """
       INSERT INTO zerver_archiveattachment_messages (id, archiveattachment_id, archivemessage_id)
       SELECT zerver_attachment_messages.id, zerver_attachment_messages.attachment_id,
           zerver_attachment_messages.message_id
       FROM zerver_attachment_messages
       INNER JOIN zerver_message ON zerver_message.id = zerver_attachment_messages.message_id
       INNER JOIN zerver_usermessage ON zerver_message.id = zerver_usermessage.message_id
       INNER JOIN zerver_userprofile ON zerver_usermessage.user_profile_id = zerver_userprofile.id
       INNER JOIN zerver_realm ON zerver_userprofile.realm_id = zerver_realm.id
       WHERE zerver_realm.message_retention_days IS NOT NULL
            AND EXTRACT(DAY FROM (CURRENT_DATE - zerver_message.pub_date)) >= zerver_realm.message_retention_days
            AND zerver_attachment_messages.id NOT IN (SELECT id FROM zerver_archiveattachment_messages)
       GROUP BY zerver_attachment_messages.id
       """
    with connection.cursor() as cursor:
        cursor.execute(query)


def delete_expired_messages():
    # type: () -> None
    removing_messages = Message.objects.filter(
        usermessage__isnull=True, id__in=ArchiveMessage.objects.all())
    removing_messages.delete()


def delete_expired_user_messages():
    # type: () -> None
    removing_user_messages = UserMessage.objects.filter(
        id__in=ArchiveUserMessage.objects.all()
    )
    removing_user_messages.delete()


def delete_expired_attachments():
    # type: () -> None
    attachments_to_remove = Attachment.objects.filter(
        messages__isnull=True, id__in=ArchiveAttachment.objects.all())
    attachments_to_remove.delete()


def archive_messages():
    # type: () -> None
    move_expired_messages_to_archive()
    move_expired_user_messages_to_archive()
    move_expired_attachments_to_archive()
    move_expired_attachments_message_rows_to_archive()
    delete_expired_user_messages()
    delete_expired_messages()
    delete_expired_attachments()


def delete_expired_archived_attachments():
    # type: () -> None
    expired_date = timezone.now() - timedelta(days=settings.ARCHIVED_DATA_RETENTION_DAYS)
    arc_attachments = ArchiveAttachment.objects \
        .filter(archived_date__lt=expired_date, messages__isnull=True) \
        .exclude(id__in=Attachment.objects.all())
    for arc_att in arc_attachments:
        delete_message_image(arc_att.path_id)
    arc_attachments.delete()


def delete_expired_archived_data():
    # type: () -> None
    arc_expired_date = timezone.now() - timedelta(days=settings.ARCHIVED_DATA_RETENTION_DAYS)
    ArchiveUserMessage.objects.filter(archived_date__lt=arc_expired_date).delete()
    ArchiveMessage.objects.filter(archived_date__lt=arc_expired_date,
                                  archiveusermessage__isnull=True).delete()
    delete_expired_archived_attachments()


def restore_archived_messages_by_realm(realm_id):
    # type: (int) -> None
    query = """
        INSERT INTO zerver_message ({dst_fields})
        SELECT {src_fields}
        FROM zerver_archivemessage
        INNER JOIN zerver_archiveusermessage ON zerver_archivemessage.id = zerver_archiveusermessage.message_id
        INNER JOIN zerver_userprofile ON zerver_archiveusermessage.user_profile_id = zerver_userprofile.id
        INNER JOIN zerver_realm ON zerver_userprofile.realm_id = zerver_realm.id
        WHERE zerver_realm.id = {realm_id}
              AND zerver_archivemessage.id NOT IN (SELECT ID FROM zerver_message)
        GROUP BY zerver_archivemessage.id
    """
    move_rows(ArchiveMessage, Message._meta.fields, query, realm_id=realm_id)


def restore_archived_usermessages_by_realm(realm_id):
    # type: (int) -> None
    query = """
        INSERT INTO zerver_usermessage ({dst_fields})
        SELECT {src_fields}
        FROM zerver_archiveusermessage
        INNER JOIN zerver_userprofile ON zerver_archiveusermessage.user_profile_id = zerver_userprofile.id
        INNER JOIN zerver_realm ON zerver_userprofile.realm_id = zerver_realm.id
        WHERE zerver_realm.id = {realm_id}
             AND zerver_archiveusermessage.id NOT IN (SELECT id FROM zerver_usermessage)
             AND zerver_archiveusermessage.message_id IN (SELECT id from zerver_message)
        """
    move_rows(ArchiveUserMessage, UserMessage._meta.fields, query, realm_id=realm_id)


def restore_archived_attachments_by_realm(realm_id):
    # type: (int) -> None
    query = """
       INSERT INTO zerver_attachment ({dst_fields})
       SELECT {src_fields}
       FROM zerver_archiveattachment
       INNER JOIN zerver_archiveattachment_messages
           ON zerver_archiveattachment_messages.archiveattachment_id = zerver_archiveattachment.id
       INNER JOIN zerver_archivemessage ON zerver_archivemessage.id = zerver_archiveattachment_messages.archivemessage_id
       INNER JOIN zerver_archiveusermessage ON zerver_archivemessage.id = zerver_archiveusermessage.message_id
       INNER JOIN zerver_userprofile ON zerver_archiveusermessage.user_profile_id = zerver_userprofile.id
       INNER JOIN zerver_realm ON zerver_userprofile.realm_id = zerver_realm.id
       WHERE zerver_realm.id = {realm_id}
            AND zerver_archiveattachment.id NOT IN (SELECT id FROM zerver_attachment)
       GROUP BY zerver_archiveattachment.id
       """
    move_rows(ArchiveAttachment, Attachment._meta.fields, query, realm_id=realm_id)


def restore_archived_attachments_message_rows_by_realm(realm_id):
    # type: (int) -> None
    query = """
       INSERT INTO zerver_attachment_messages (id, attachment_id, message_id)
       SELECT zerver_archiveattachment_messages.id, zerver_archiveattachment_messages.archiveattachment_id,
           zerver_archiveattachment_messages.archivemessage_id
       FROM zerver_archiveattachment_messages
       INNER JOIN zerver_archivemessage ON zerver_archivemessage.id = zerver_archiveattachment_messages.archivemessage_id
       INNER JOIN zerver_archiveusermessage ON zerver_archivemessage.id = zerver_archiveusermessage.message_id
       INNER JOIN zerver_userprofile ON zerver_archiveusermessage.user_profile_id = zerver_userprofile.id
       INNER JOIN zerver_realm ON zerver_userprofile.realm_id = zerver_realm.id
       WHERE zerver_realm.id = {realm_id}
            AND zerver_archiveattachment_messages.id NOT IN (SELECT id FROM zerver_attachment_messages)
       GROUP BY zerver_archiveattachment_messages.id
       """

    with connection.cursor() as cursor:
        cursor.execute(query.format(realm_id=realm_id))


def delete_archived_data_by_realm(realm_id):
    # type: (int) -> None
    ArchiveUserMessage.objects.filter(user_profile__realm__id=realm_id).delete()
    ArchiveMessage.objects.filter(archiveusermessage__isnull=True).delete()
    ArchiveAttachment.objects.filter(messages__isnull=True).delete()


def restore_realm_archived_data(realm_id):
    # type: (int) -> None
    restore_archived_messages_by_realm(realm_id)
    restore_archived_usermessages_by_realm(realm_id)
    restore_archived_attachments_by_realm(realm_id)
    restore_archived_attachments_message_rows_by_realm(realm_id)
    realm = Realm.objects.get(id=realm_id)
    realm.message_retention_days = None
    realm.save()
