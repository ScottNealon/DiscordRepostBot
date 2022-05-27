SELECT messageID,
    channelID,
    memberID,
    timestamp
FROM urls
WHERE url = :url;