CREATE TABLE version(version INT NOT NULL);
CREATE TABLE updates(
    oldestUpdate FLOAT NOT NULL,
    lastUpdate FLOAT NOT NULL
);
CREATE TABLE active(active INT NOT NULL);
CREATE TABLE blacklistedChannels(id INT NOT NULL);
CREATE TABLE emoji(emoji VARCHAR NOT NULL);
CREATE TABLE members(id INT NOT NULL PRIMARY KEY);
CREATE TABLE urls(
    url VARCHAR NOT NULL PRIMARY KEY,
    messageID INT NOT NULL,
    channelID INT NOT NULL,
    memberID INT NOT NULL,
    timestamp FLOAT NOT NULL,
    FOREIGN KEY (memberID) REFERENCES members(id)
);
CREATE TABLE reposts(
    messageID INT NOT NULL,
    channelID INT NOT NULL,
    memberID INT NOT NULL,
    url VARCHAR NOT NULL,
    FOREIGN KEY (memberID) REFERENCES members(id),
    FOREIGN KEY (url) REFERENCES urls(url)
);
/* Populate tables */
INSERT INTO version (version)
VALUES (:newest_version);
INSERT INTO updates (oldestUpdate, lastUpdate)
VALUES (:now, :now);
INSERT INTO active (active)
VALUES (1);
INSERT INTO emoji (emoji)
VALUES ("recycle")