UPDATE urls
SET messageID = :messageID,
    channelID = :channelID,
    memberID = :memberID,
    timestamp = :timestamp
WHERE url = :url