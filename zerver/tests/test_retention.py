# -*- coding: utf-8 -*-
from __future__ import absolute_import
import mock

from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from zerver.lib.test_classes import ZulipTestCase
from zerver.lib.upload import create_attachment
from zerver.models import (Message, Realm, Recipient, UserProfile, ArchiveUserMessage,
                           ArchiveMessage, UserMessage, get_user_profile_by_email,
                           ArchiveAttachment, Attachment)
from zerver.lib.retention import (move_expired_messages_to_archive,
                                  move_expired_user_messages_to_archive, delete_expired_messages,
                                  delete_expired_user_messages, archive_messages,
                                  move_expired_attachments_to_archive,
                                  move_expired_attachments_message_rows_to_archive,
                                  delete_expired_archived_data, restore_archived_messages_by_realm,
                                  restore_archived_usermessages_by_realm,
                                  restore_archived_attachments_by_realm,
                                  restore_archived_attachments_message_rows_by_realm,
                                  restore_realm_archived_data)

from six.moves import range

from typing import Any


class TestRetentionLib(ZulipTestCase):
    """
        Test receiving expired messages retention tool.
    """

    def setUp(self):
        # type: () -> None
        super(TestRetentionLib, self).setUp()
        self.zulip_realm = self._set_realm_message_retention_value('zulip.com', 30)
        self.mit_realm = self._set_realm_message_retention_value('mit.edu', 100)

    @staticmethod
    def _set_realm_message_retention_value(domain, retention_period):
        # type: (str, int) -> Realm
        # Change retention period for certain realm.
        realm = Realm.objects.filter(domain=domain).first()
        realm.message_retention_days = retention_period
        realm.save()
        return realm

    @staticmethod
    def _change_msgs_pub_date(msgs_ids, pub_date):
        # type: (List[int], datetime) -> Any
        # Update message pud_date value.
        msgs = Message.objects.filter(id__in=msgs_ids).order_by('id')
        msgs.update(pub_date=pub_date)
        return msgs

    def _make_mit_msgs(self, msg_qauntity, pub_date):
        # type: (int, datetime) -> Any
        # Send messages from mit.edu realm and change messages pub_date.
        sender = UserProfile.objects.filter(email='espuser@mit.edu').first()
        recipient = UserProfile.objects.filter(email='starnine@mit.edu').first()
        msgs_ids = [self.send_message(sender.email, recipient.email, Recipient.PERSONAL) for i in
                    range(msg_qauntity)]
        mit_msgs = self._change_msgs_pub_date(msgs_ids, pub_date)
        return mit_msgs

    def _send_cross_realm_message(self):
        # type: () -> int
        # Send message from bot to users from different realm.
        bot_email = 'notification-bot@zulip.com'
        get_user_profile_by_email(bot_email)
        mit_user = UserProfile.objects.filter(realm=self.mit_realm).first()
        return self.send_message(bot_email, [mit_user.email],
                                 Recipient.PERSONAL)

    def _check_archive_data_by_realm(self, exp_msgs, realm):
        # type: (Any, Realm) -> None
        self._check_archive_messages_ids_by_realm(
            [msg.id for msg in exp_msgs.order_by('id')],
            realm
        )
        user_messages = UserMessage.objects.filter(message__in=exp_msgs).order_by('id')
        archive_user_messages = ArchiveUserMessage.objects.filter(
            user_profile__realm=realm).order_by('id')
        self.assertEqual(
            [user_msg.id for user_msg in user_messages],
            [arc_user_msg.id for arc_user_msg in archive_user_messages]
        )

    def _check_archive_messages_ids_by_realm(self, exp_message_ids, realm):
        # type: (List[int], Realm) -> None
        arc_messages = ArchiveMessage.objects.filter(
            archiveusermessage__user_profile__realm=realm).distinct('id').order_by('id')
        self.assertEqual(
            exp_message_ids,
            [arc_msg.id for arc_msg in arc_messages]
        )

    def _send_msgs_with_attachments(self):
        # type: () -> Dict[str, int]
        sender_email = "hamlet@zulip.com"
        user_profile = get_user_profile_by_email(sender_email)
        dummy_files = [
            ('zulip.txt', '1/31/4CBjtTLYZhk66pZrF8hnYGwc/zulip.txt'),
            ('temp_file.py', '1/31/4CBjtTLYZhk66pZrF8hnYGwc/temp_file.py'),
            ('abc.py', '1/31/4CBjtTLYZhk66pZrF8hnYGwc/abc.py')
        ]

        for file_name, path_id in dummy_files:
            create_attachment(file_name, path_id, user_profile)

        self.subscribe_to_stream(sender_email, "Denmark")
        body = "Some files here ...[zulip.txt](http://localhost:9991/user_uploads/1/31/4CBjtTLYZhk66pZrF8hnYGwc/zulip.txt)" + \
               "http://localhost:9991/user_uploads/1/31/4CBjtTLYZhk66pZrF8hnYGwc/temp_file.py.... Some more...." + \
               "http://localhost:9991/user_uploads/1/31/4CBjtTLYZhk66pZrF8hnYGwc/abc.py"

        expired_message_id = self.send_message(sender_email, "Denmark", Recipient.STREAM, body,
                                               "test")
        actual_message_id = self.send_message(sender_email, "Denmark", Recipient.STREAM, body,
                                              "test")
        self._change_msgs_pub_date([expired_message_id], timezone.now() - timedelta(days=101))
        return {'expired_message_id': expired_message_id, 'actual_message_id': actual_message_id}

    def _add_expired_date_to_archive_data(self):
        # type: () -> None
        arc_expired_date = timezone.now() - timedelta(
            days=settings.ARCHIVED_DATA_RETENTION_DAYS + 2)
        ArchiveMessage.objects.update(archived_date=arc_expired_date)
        ArchiveUserMessage.objects.update(archived_date=arc_expired_date)
        ArchiveAttachment.objects.update(archived_date=arc_expired_date)

    def _check_cross_realm_messages_archiving(self, arc_user_msg_qty, period, realm=None):
        # type: (int, int, Realm) -> int
        sended_message_id = self._send_cross_realm_message()
        all_user_messages_qty = UserMessage.objects.count()
        self._change_msgs_pub_date([sended_message_id], timezone.now() - timedelta(days=period))
        move_expired_messages_to_archive()
        move_expired_user_messages_to_archive()
        user_messages_sended = UserMessage.objects.order_by('id').filter(
            message_id=sended_message_id)
        archived_messages = ArchiveMessage.objects.all()
        archived_user_messages = ArchiveUserMessage.objects.order_by('id')
        self.assertEqual(user_messages_sended.count(), 2)
        # Compare archived messages and user messages
        # with expired sended messages.
        self.assertEqual(archived_messages.count(), 1)
        self.assertEqual(archived_user_messages.count(), arc_user_msg_qty)
        if realm:
            user_messages_sended = user_messages_sended.filter(user_profile__realm=self.zulip_realm)
        self.assertEqual(
            [arc_user_msg.id for arc_user_msg in archived_user_messages],
            [user_msg.id for user_msg in user_messages_sended]
        )
        delete_expired_user_messages()
        delete_expired_messages()
        # Check messages and user messages after deleting expired messages
        # from the main tables.
        self.assertEqual(
            UserMessage.objects.filter(message_id=sended_message_id).count(),
            2 - arc_user_msg_qty)
        self.assertEqual(
            UserMessage.objects.count(),
            all_user_messages_qty - arc_user_msg_qty)
        return sended_message_id

    def _make_expired_messages(self):
        # type: () -> Dict[str,List[int]]
        # Create messages with expired date
        exp_mit_msgs = self._make_mit_msgs(3, timezone.now() - timedelta(days=101))
        exp_mit_msgs_ids = [msg.id for msg in exp_mit_msgs.order_by('id')]
        self._make_mit_msgs(4, timezone.now() - timedelta(days=50))
        exp_zulip_msgs_ids = list(Message.objects.order_by('id').filter(
            sender__realm=self.zulip_realm).values_list('id', flat=True)[3:10])
        # Add expired zulip mesages ids.
        self._change_msgs_pub_date(exp_zulip_msgs_ids,
                                   timezone.now() - timedelta(days=31))
        return {
            "mit_msgs_ids": exp_mit_msgs_ids,
            "zulip_msgs_ids": exp_zulip_msgs_ids
        }

    def create_user(self, email):
        # type: (str) -> UserProfile
        # Create user by email
        username, _ = email.split('@')
        self.register(username, 'test')
        return get_user_profile_by_email(email)

    def test_no_expired_messages(self):
        # type: () -> None
        move_expired_messages_to_archive()
        move_expired_user_messages_to_archive()
        self.assertEqual(ArchiveUserMessage.objects.count(), 0)
        self.assertEqual(ArchiveMessage.objects.count(), 0)

    def test_expired_msgs_in_each_realm(self):
        # type: () -> None
        # Check result realm messages order and result content
        # when all realm has expired messages.
        exp_messages_ids = []
        exp_mit_msgs = self._make_mit_msgs(3, timezone.now() - timedelta(days=101))
        exp_messages_ids.extend([msg.id for msg in exp_mit_msgs.order_by('id')])
        self._make_mit_msgs(4, timezone.now() - timedelta(days=50))
        zulip_msgs_ids = list(Message.objects.order_by('id').filter(
            sender__realm=self.zulip_realm).values_list('id', flat=True)[3:10])
        exp_messages_ids.extend(zulip_msgs_ids)
        exp_zulip_msgs = self._change_msgs_pub_date(zulip_msgs_ids,
                                                    timezone.now() - timedelta(days=31))
        move_expired_messages_to_archive()
        move_expired_user_messages_to_archive()
        self.assertEqual(ArchiveMessage.objects.count(), len(exp_messages_ids))
        self.assertEqual(
            ArchiveUserMessage.objects.count(),
            UserMessage.objects.filter(message_id__in=exp_messages_ids).count()
        )
        # Compare expected messages ids with archived messages by realm.
        self._check_archive_data_by_realm(exp_mit_msgs, self.mit_realm)
        self._check_archive_data_by_realm(exp_zulip_msgs, self.zulip_realm)

    def test_expired_messages_in_one_realm(self):
        # type: () -> None
        # Check realm with expired messages and messages
        # with one day to expiration data.
        exp_mit_msgs = self._make_mit_msgs(5, timezone.now() - timedelta(days=101))
        move_expired_messages_to_archive()
        move_expired_user_messages_to_archive()
        archived_user_messages = ArchiveUserMessage.objects.all()
        self.assertEqual(ArchiveMessage.objects.count(), 5)
        self.assertEqual(archived_user_messages.count(), 10)
        # Compare expected messages ids with archived messages in mit realm
        self._check_archive_data_by_realm(exp_mit_msgs, self.mit_realm)
        # Check no archive messages for zulip realm.
        self.assertEqual(
            ArchiveMessage.objects.filter(
                archiveusermessage__user_profile__realm=self.zulip_realm).count(),
            0
        )
        self.assertEqual(
            ArchiveUserMessage.objects.filter(user_profile__realm=self.zulip_realm).count(),
            0
        )

    def test_cross_realm_messages_archiving_one_realm_expired(self):
        # type: () -> None
        # Check archiving messages which is sent to different realms
        # and expired just on on one of them.
        arc_msg_id = self._check_cross_realm_messages_archiving(1, 31, realm=self.zulip_realm)
        self.assertTrue(Message.objects.filter(id=arc_msg_id).exists())

    def test_cross_realm_messages_archiving_two_realm_expired(self):
        # type: () -> None
        # Check archiving cross realm message wich is expired on both realms.
        arc_msg_id = self._check_cross_realm_messages_archiving(2, 101)
        self.assertFalse(Message.objects.filter(id=arc_msg_id).exists())

    def test_archive_message_tool(self):
        # type: () -> None
        # Check archiving tool.
        exp_msgs_ids_dict = self._make_expired_messages()  # List of expired messages ids.
        sended_cross_realm_message_id = self._send_cross_realm_message()
        exp_msgs_ids_dict['mit_msgs_ids'].append(sended_cross_realm_message_id)
        # Add cross realm message id.
        self._change_msgs_pub_date(
            [sended_cross_realm_message_id],
            timezone.now() - timedelta(days=101)
        )
        exp_msgs_ids = exp_msgs_ids_dict['mit_msgs_ids'] + exp_msgs_ids_dict['zulip_msgs_ids']
        # Get expired user messages by message ids
        exp_user_msgs_ids = list(UserMessage.objects.filter(
            message_id__in=exp_msgs_ids).order_by('id').values_list('id', flat=True))
        msgs_qty = Message.objects.count()
        archive_messages()
        # Compare archived messages and user messages with expired messages
        self.assertEqual(ArchiveMessage.objects.count(), len(exp_msgs_ids))
        self.assertEqual(ArchiveUserMessage.objects.count(), len(exp_user_msgs_ids))
        # Check left messages after removing expired messages from main tables
        self.assertEqual(Message.objects.count(), msgs_qty - ArchiveMessage.objects.count())
        self.assertEqual(
            Message.objects.filter(id__in=exp_msgs_ids_dict['zulip_msgs_ids']).count(), 0)
        self.assertEqual(
            Message.objects.filter(id__in=exp_msgs_ids_dict['mit_msgs_ids']).count(), 0)
        self.assertEqual(
            Message.objects.filter(id__in=exp_msgs_ids_dict['zulip_msgs_ids']).count(), 0)
        exp_msgs_ids_dict['zulip_msgs_ids'].append(sended_cross_realm_message_id)
        # Check archived messages by realm
        self._check_archive_messages_ids_by_realm(
            exp_msgs_ids_dict['zulip_msgs_ids'], self.zulip_realm)
        self._check_archive_messages_ids_by_realm(
            exp_msgs_ids_dict['mit_msgs_ids'], self.mit_realm)

    def test_moving_attachments_to_archive_without_removing(self):
        # type: () -> None
        msgs_ids = self._send_msgs_with_attachments()
        move_expired_messages_to_archive()
        move_expired_user_messages_to_archive()
        move_expired_attachments_to_archive()
        move_expired_attachments_message_rows_to_archive()
        archived_attachment = ArchiveAttachment.objects.all()
        self.assertEqual(archived_attachment.count(), 3)
        self.assertEqual(
            list(archived_attachment.distinct('messages__id').values_list('messages__id',
                                                                          flat=True)),
            [msgs_ids['expired_message_id']])

    def test_archiving_attachments_with_removing(self):
        # type: () -> None
        msgs_ids = self._send_msgs_with_attachments()

        archive_messages()
        archived_attachment = ArchiveAttachment.objects.all()
        attachment = Attachment.objects.all()
        self.assertEqual(archived_attachment.count(), 3)
        self.assertEqual(
            list(archived_attachment.distinct('messages__id').values_list('messages__id',
                                                                          flat=True)),
            [msgs_ids['expired_message_id']])
        self.assertEqual(attachment.count(), 3)
        self._change_msgs_pub_date([msgs_ids['actual_message_id']],
                                   timezone.now() - timedelta(days=101))
        archive_messages()
        self.assertEqual(attachment.count(), 0)
        self.assertEqual(
            list(archived_attachment.distinct('messages__id').order_by('messages__id').values_list(
                'messages__id', flat=True)),
            sorted(msgs_ids.values()))

    def test_delete_archived_data(self):
        # type: () -> None
        msgs_ids = self._send_msgs_with_attachments()
        exp_msgs_ids_dict = self._make_expired_messages()
        archive_messages()

        self.assertEqual(
            ArchiveMessage.objects.count(),
            len(exp_msgs_ids_dict['zulip_msgs_ids'] + exp_msgs_ids_dict['mit_msgs_ids']) + 1)
        self.assertEqual(
            ArchiveAttachment.objects.count(),
            3
        )
        self._add_expired_date_to_archive_data()

        delete_expired_archived_data()
        self.assertEqual(
            ArchiveAttachment.objects.count(),
            3
        )
        self.assertEqual(
            ArchiveMessage.objects.count(),
            0)
        self._change_msgs_pub_date([msgs_ids['actual_message_id']],
                                   timezone.now() - timedelta(days=101))
        archive_messages()
        self._add_expired_date_to_archive_data()
        with mock.patch('zerver.lib.upload.LocalUploadBackend.delete_message_image',
                        return_value=True):
            delete_expired_archived_data()
        self.assertEqual(
            ArchiveAttachment.objects.count(),
            0
        )

    def test_restoring_archived_messages(self):
        # type: () -> None
        exp_msgs_ids_dict = self._make_expired_messages()
        archive_messages()
        self.assertEqual(
            ArchiveMessage.objects.filter(Q(id__in=exp_msgs_ids_dict['zulip_msgs_ids']) | Q(
                id__in=exp_msgs_ids_dict['mit_msgs_ids'])).count(),
            len(exp_msgs_ids_dict['zulip_msgs_ids']) + len(exp_msgs_ids_dict['mit_msgs_ids'])
        )
        self.assertEqual(
            Message.objects.filter(Q(id__in=exp_msgs_ids_dict['zulip_msgs_ids']) | Q(
                id__in=exp_msgs_ids_dict['mit_msgs_ids'])).count(),
            0
        )
        restore_archived_messages_by_realm(self.zulip_realm.id)
        self.assertEqual(
            Message.objects.filter(id__in=exp_msgs_ids_dict['zulip_msgs_ids']).count(),
            len(exp_msgs_ids_dict['zulip_msgs_ids'])
        )
        self.assertEqual(
            Message.objects.filter(id__in=exp_msgs_ids_dict['mit_msgs_ids']).count(),
            0
        )
        restore_archived_messages_by_realm(self.mit_realm.id)
        self.assertEqual(
            Message.objects.filter(id__in=exp_msgs_ids_dict['mit_msgs_ids']).count(),
            len(exp_msgs_ids_dict['mit_msgs_ids'])
        )

    def test_restoring_archived_user_messages(self):
        # type: () -> None
        exp_msgs_ids_dict = self._make_expired_messages()
        archive_messages()
        zulip_archived_user_messages = ArchiveUserMessage.objects.filter(
            message_id__in=exp_msgs_ids_dict['zulip_msgs_ids'])
        mit_archived_user_messages = ArchiveUserMessage.objects.filter(
            message_id__in=exp_msgs_ids_dict['mit_msgs_ids'])
        self.assertEqual(
            UserMessage.objects.filter(Q(id__in=zulip_archived_user_messages) or Q(
                id__in=mit_archived_user_messages)).count(),
            0
        )
        restore_archived_messages_by_realm(self.zulip_realm.id)
        restore_archived_usermessages_by_realm(self.zulip_realm.id)
        self.assertEqual(
            UserMessage.objects.filter(
                id__in=zulip_archived_user_messages).count(),
            zulip_archived_user_messages.count()
        )
        self.assertEqual(
            UserMessage.objects.filter(
                id__in=mit_archived_user_messages).count(),
            0
        )
        restore_archived_messages_by_realm(self.mit_realm.id)
        restore_archived_usermessages_by_realm(self.mit_realm.id)
        self.assertEqual(
            UserMessage.objects.filter(
                id__in=mit_archived_user_messages).count(),
            mit_archived_user_messages.count()
        )

    def test_restoring_archived_attachments(self):
        # type: () -> None
        msgs_with_attachments_ids = self._send_msgs_with_attachments()
        self._change_msgs_pub_date([msgs_with_attachments_ids['actual_message_id']],
                                   timezone.now() - timedelta(days=101))
        archive_messages()
        self.assertEqual(ArchiveAttachment.objects.count(), 3)
        self.assertEqual(Attachment.objects.count(), 0)
        restore_archived_attachments_by_realm(self.zulip_realm.id)
        self.assertEqual(Attachment.objects.count(), 3)

    def test_restoring_archived_attachments_message(self):
        # type: () -> None
        msgs_with_attachments_ids = self._send_msgs_with_attachments()
        self._change_msgs_pub_date([msgs_with_attachments_ids['actual_message_id']],
                                   timezone.now() - timedelta(days=101))
        archive_messages()
        self.assertEqual(ArchiveAttachment.objects.count(), 3)
        self.assertEqual(ArchiveAttachment.objects.filter(messages__isnull=False).count(), 6)
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(Attachment.objects.filter(messages__isnull=False).count(), 0)
        restore_archived_attachments_by_realm(self.zulip_realm.id)
        self.assertEqual(Attachment.objects.filter(messages__isnull=False).count(), 0)
        restore_archived_messages_by_realm(self.zulip_realm.id)
        restore_archived_attachments_message_rows_by_realm(self.zulip_realm.id)
        self.assertEqual(Attachment.objects.count(), 3)
        self.assertEqual(Attachment.objects.filter(messages__isnull=False).count(), 6)

    def test_restore_realm_archived_data_tool(self):
        # type: () -> None
        msgs_with_attachments_ids = self._send_msgs_with_attachments()
        self._change_msgs_pub_date([msgs_with_attachments_ids['actual_message_id']],
                                   timezone.now() - timedelta(days=101))
        exp_msgs_ids_dict = self._make_expired_messages()
        self._change_msgs_pub_date([msgs_with_attachments_ids['actual_message_id']],
                                   timezone.now() - timedelta(days=101))
        archive_messages()
        self.assertEqual(Message.objects.filter(
            Q(id__in=[msgs_with_attachments_ids['expired_message_id']]) | Q(
                id__in=exp_msgs_ids_dict['mit_msgs_ids']) | Q(
                id__in=exp_msgs_ids_dict['zulip_msgs_ids'])).count(), 0)
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(UserMessage.objects.filter(
            Q(message_id__in=[msgs_with_attachments_ids['expired_message_id']]) | Q(
                message_id__in=exp_msgs_ids_dict['mit_msgs_ids']) | Q(
                message_id__in=exp_msgs_ids_dict['zulip_msgs_ids'])).count(), 0)
        restore_realm_archived_data(self.zulip_realm.id)
        self.assertEqual(
            Message.objects.filter(
                Q(id__in=[msgs_with_attachments_ids['expired_message_id']]) | Q(
                    id__in=exp_msgs_ids_dict['zulip_msgs_ids'])).count(),
            len(exp_msgs_ids_dict['zulip_msgs_ids']) + 1)
        self.assertEqual(
            UserMessage.objects.filter(
                Q(message_id__in=[msgs_with_attachments_ids['expired_message_id']]) | Q(
                    message_id__in=exp_msgs_ids_dict['zulip_msgs_ids'])).count(),
            ArchiveUserMessage.objects.filter(
                Q(message_id__in=[msgs_with_attachments_ids['expired_message_id']]) | Q(
                    message_id__in=exp_msgs_ids_dict['zulip_msgs_ids'])).count())
        self.assertEqual(Attachment.objects.count(), 3)
        realm = Realm.objects.get(id=self.zulip_realm.id)
        self.assertIsNone(realm.message_retention_days)
