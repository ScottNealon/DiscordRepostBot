CREATE TABLE version(version VARCHAR NOT NULL);
INSERT INTO version (version)
VALUES ("{current_database_version}");
CREATE TABLE updates(
    oldestUpdate FLOAT NOT NULL,
    lastUpdate FLOAT NOT NULL
);
INSERT INTO updates (oldestUpdate, lastUpdate)
VALUES ({ now }, { now });
CREATE TABLE prefix(prefix VARCHAR NOT NULL);
INSERT INTO prefix (prefix)
VALUES ("$repost");
CREATE TABLE active(active INT NOT NULL);
INSERT INTO active (active)
VALUES (1);
CREATE TABLE blacklistedChannels(channelID INT NOT NULL);