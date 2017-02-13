# Retention policy


## Overview

This document describes the retention policy feature. If you set the
retention period in the realm (organization) settings, you can use
these tools to move old messages and attachments to archive tables,
restore messages from the archive back into the main tables, and
finally delete archived messages and attachments from the archive
tables after the retention period expires.

Zulip offers the console commands
`management/commands/archive_messages.py` to move expired data to
archive tables, and `management/commands/remove_old_archived_data.py`
to remove archived messages and archived attachments permanently.

## Front-end admin settings

To enable the realm retention policy, you should add a value to the
`Retention period for messages in days` field in the "administration"
part of the "Organization settings" screen.

To disable this feature, leave this field empty; Zulip will simply
accumulate messages and the console commands will not work.


## Database tables storing archive data

Before deleting the old data, Zulip first moves it to archiving
tables. It lives there in case you want to restore it, or until you
delete it. The tables are:

  `zerver.models.ArchiveMessage`
  `zerver.models.ArchiveUserMessage`
  `zerver.models.ArchiveAttachment`

These Django models are inherited from abstract model classes which
are common for newer and archived records.


### Moving expired messages and attachments to archive

Retention tools methods:


  `zerver.lib.retention.move_expired_messages_to_archive`
  `zerver.lib.retention.move_expired_user_messages_to_archive`
  `zerver.lib.retention.move_expired_attachments_to_archive`
  `zerver.lib.retention.move_expired_attachments_message_rows_to_archive`
  `zerver.lib.retention.archive_messages`

Since the Django ORM is not as flexible as raw SQL language queries
are, we had to use SQL queries and a database connector directly in
these tools for moving data to archive tables. This decision lets
Zulip move the data in one query.

Messages and attachments are moved to archive when all `user_messages`
related to them are moved to archive tables.

Zulip uses `archive_messages` as a result method which contains
archiving and removal methods in proper sequence.

Archiving tables are cleaned when `ARCHIVE_DATA_RETENTION_DAYS` from
project settings is expired for table record by launching
`management/commands/remove_old_archived_data.py` management command.

### Deleting expired messages and attachments

Retention tools methods:


  `zerver.lib.retention.delete_expired_messages`
  `zerver.lib.retention.delete_expired_user_messages`
  `zerver.lib.retention.delete_expired_attachments`

Records are removed from the actual tables when they don't have related
objects. There shouldn't be any related `user_messages` records for
messages and there shouldn't be any related`messages` for attachments.

### Deleting expired archive data

Retention tools methods:


  `zerver.lib.retention.delete_expired_archived_attachments`
  `zerver.lib.retention.delete_expired_archived_data`

If the restoring of archive messages and attachments is not required for
`ARCHIVE_DATA_RETENTION_DAYS` period, the archived data should be
removed. To remove this data `delete_expired_archived_data`
method is used, which includes `delete_expired_archived_attachments`
method to remove attachments.


## Cron jobs

Cron file:

  `puppet/zulip/files/cron.d/archive-messages`

This file contains two cron jobs. The first one is used to launch the
archiving manage console command and the other one to remove expired
archived data.

The order of launching jobs is important, as the archiving job
should clean all the related objects at this moment. In other case,
it will be done next time.

## Restoring of archived data by Realm

Retention tools methods:


  `zerver.lib.retention.restore_archived_messages_by_realm`
  `zerver.lib.retention.restore_archived_usermessages_by_realm`
  `zerver.lib.retention.restore_archived_attachments_by_realm`
  `zerver.lib.retention.restore_archived_attachments_message_rows_by_realm`

These tools restore archived data by realm without removing records
from archived tables. Archived data is removed by deleting tools.

To restore archived data you should run management console command,
which is located:

  `zerver.lib.retention.restore_realm_archived_data`

Also it disables retention feature for Realm by adding empty value to
`message_retention_days` field. Tools order in this command is
important too.

Example of command:

  `./management restore_realm_archived_data zulip.com`


## Code and tests

The retention policy code (the code the management commands execute)
is located in `zerver/lib/retention.py`

Test cases are described in `zerver/tests/test_retention.py`.
