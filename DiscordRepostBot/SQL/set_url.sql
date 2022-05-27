UPDATE urls
SET messageID = :messageID,
    channelID = :channelID,
    timestamp = :timestamp
WHERE url = :url