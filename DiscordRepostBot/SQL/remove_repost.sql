DELETE FROM reposts
WHERE messageID = :messageID,
    url = :url;