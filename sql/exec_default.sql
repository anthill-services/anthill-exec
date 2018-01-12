CREATE TABLE `exec_default` (
  `gamespace_id` int(11) unsigned NOT NULL,
  `repository_url` varchar(255) NOT NULL DEFAULT '',
  `repository_branch` varchar(255) NOT NULL DEFAULT 'master',
  `ssh_private_key` varchar(4096) NOT NULL DEFAULT '',
  `repository_commit` varchar(64) DEFAULT NULL,
  UNIQUE KEY `gamespace_id` (`gamespace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
