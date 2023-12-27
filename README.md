# zKillboardMonitor

zKillboardMonitor is written in python and designed to run on Linux as a systemD service.

Feeds can be defined in the configuration.json along with a webhook to alert to.
Each feed should have a type to filter against for relevance.

## Configuration

All feeds should contain the following fields:

- name: A friendly name for the feed, used largely for logging purposes
- webhook: The full webhook URL (Only discord webhooks are supported at present)
- include_empty_pods: A boolean [true,false] which will determine whether empty pod killmails are discarded.
- feed_type: Valid options are: [entity, location, label]

### Entity Feeds

All entity feeds require the following fields:

- entity_type: One of [alliance_id, corporation_id, character_id]
- entity_id: The integer ID value for the entity, this can be taken from the zKillboard URL

Additional feed types may be added in the future but none are planned at present.
Proximity/range style feeds are unlikely to be implemented due to the overhead involved

### Location Feeds

All location feeds require the following fields:

- location_type: One of [system_id, constellation_id, region_id]
- location_id: The integer ID value of the location, this can be taken from the zKillboard URL

Use of constellation_id and region_id are discouraged as they require significant additional overhead for processing killmails.

### Label Feeds

Label feeds look to match labels added to the kill by zKillboard.
These are not guarenteed to be reliable in any way.

All label feeds require the following field:

- zkb_label: The label from zKillboard

Known options are as follows:
- [highsec,lowsec,nullsec,w-space,abyssal]
- [solo,2+,5+,10+,25+,50+,100+,1000+]
- [awox,ganked,npc,pvp,padding]
- [1b+, 5b+,10b+,100b+]
- [cat:65,capital]
