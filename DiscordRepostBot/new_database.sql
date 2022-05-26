CREATE TABLE version(version INT NOT NULL);
CREATE TABLE updates(
    oldestUpdate FLOAT NOT NULL,
    lastUpdate FLOAT NOT NULL
);
CREATE TABLE prefix(prefix VARCHAR NOT NULL);
CREATE TABLE active(active INT NOT NULL);
CREATE TABLE blacklistedChannels(channelID INT NOT NULL);
CREATE TABLE emoji(emoji VARCHAR NOT NULL);
CREATE TABLE urls(
    url VARCHAR NOT NULL,
    messageID INT NOT NULL,
    timestamp FLOAT NOT NULL,
    PRIMARY KEY (url)
);
CREATE TABLE members(
    ID INT NOT NULL,
    name VARCHAR NOT NULL,
    PRIMARY KEY (ID)
);
/* Populate tables */
INSERT INTO version (version)
VALUES (:current_database_version);
INSERT INTO updates (oldestUpdate, lastUpdate)
VALUES (:now, :now);
INSERT INTO prefix (prefix)
VALUES ("$repost");
INSERT INTO active (active)
VALUES (1);
INSERT INTO emoji (emoji)
VALUES ("recycle")