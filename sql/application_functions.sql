CREATE TABLE `application_functions` (
  `gamespace_id` int(11) unsigned NOT NULL,
  `application_name` varchar(64) NOT NULL DEFAULT '',
  `function_id` int(11) unsigned NOT NULL,
  PRIMARY KEY (`application_name`,`function_id`),
  UNIQUE KEY `gamespace_id` (`gamespace_id`,`application_name`,`function_id`),
  KEY `application_name` (`application_name`),
  KEY `function_id` (`function_id`),
  CONSTRAINT `application_functions_ibfk_1` FOREIGN KEY (`function_id`) REFERENCES `functions` (`function_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;