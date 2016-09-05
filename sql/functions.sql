CREATE TABLE `functions` (
  `function_id` int(11) unsigned NOT NULL AUTO_INCREMENT,
  `gamespace_id` int(10) unsigned NOT NULL,
  `function_name` varchar(64) NOT NULL DEFAULT '',
  `function_code` text NOT NULL,
  `function_imports` varchar(255) NOT NULL DEFAULT '',
  PRIMARY KEY (`function_id`),
  UNIQUE KEY `gamespace_id` (`gamespace_id`,`function_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;