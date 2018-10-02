CREATE TABLE `exec_application_versions` (
  `gamespace_id` int(11) unsigned NOT NULL,
  `application_name` varchar(64) NOT NULL DEFAULT '',
  `application_version` varchar(64) NOT NULL DEFAULT '',
  `repository_commit` varchar(64) NOT NULL DEFAULT '',
  UNIQUE KEY `gamespace_id` (`gamespace_id`,`application_name`,`application_version`),
  KEY `application_name` (`application_name`,`application_version`,`repository_commit`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;