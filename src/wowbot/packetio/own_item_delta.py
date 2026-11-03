"""Reviewed ItemData/ContainerData VALUES for already confirmed owned GUIDs.

Unsupported masks invalidate ownership until another verified CREATE; no
unreviewed dynamic-array offset or another player's private fields are guessed.
"""
from .own_inventory_codec import _guid, count

LAYOUT = 'WPP_12_1_OWN_INVENTORY_REVIEWED_V2'


def _mask(cursor, words):
    cursor.reset()
    presence=cursor.bits(words)
    value=sum((cursor.bits(32) if presence>>i&1 else 0) << (32*i) for i in range(words))
    cursor.reset()
    return value


def _item(cursor, own_guid):
    from .context import same_player
    mask=_mask(cursor,2)
    if mask>>41 or mask & (1<<1 | 1<<2 | 1<<17):
        raise ValueError('unreviewed own item dynamic fields')
    if (mask & sum(1<<i for i in range(3,21)) and not mask&1
            or mask & sum(1<<i for i in range(22,27)) and not mask>>21&1
            or mask & sum(1<<i for i in range(28,41)) and not mask>>27&1):
        raise ValueError('unrooted own item change mask')
    result={}
    if mask&1:
        if mask>>3&1:
            owner=cursor.guid()
            if not same_player(owner,own_guid):return {'foreign_owner':True}
        if mask>>4&1:result['container_guid']=cursor.guid()
        for i in (5,6):
            if mask>>i&1:
                from .player_quest_log import _skip_guid
                _skip_guid(cursor)
        for i,key,reader in ((7,'stack_count','u32'),(8,None,'u32'),(9,None,'u32'),
            (10,'durability','u32'),(11,'max_durability','u32'),(12,None,'u32'),(13,None,'u8'),
            (14,None,'i64'),(15,None,'u64'),(16,None,'u8')):
            if mask>>i&1:
                value=getattr(cursor,reader)()
                if key:result[key]=value
        if mask>>18&1:cursor.take(4)
        if mask>>19&1:
            cursor.take(4)
            bonuses,modifiers=count(cursor),count(cursor)
            cursor.take(bonuses*4+modifiers*5)
        if mask>>20&1:cursor.take(2)
    if mask>>21&1:
        cursor.take(sum(4 for i in range(22,27) if mask>>i&1))
    if mask>>27&1:
        for i in range(28,41):
            if not mask>>i&1:continue
            cursor.reset();enchant=cursor.bits(5);cursor.reset()
            if enchant&0x1e and not enchant&1:raise ValueError('unrooted enchantment mask')
            if enchant&1:
                cursor.take(sum(size for bit,size in ((1,4),(2,4),(3,2),(4,2)) if enchant>>bit&1))
    return result


def _container(cursor):
    mask=_mask(cursor,4)
    if mask>>101 or mask&2 and not mask&1 or mask>>3 and not mask&4:
        raise ValueError('unreviewed container change mask')
    result={}
    if mask&1 and mask&2:
        size=cursor.u32()
        if size>98:raise ValueError('invalid container capacity')
        result['num_slots']=size
    if mask&4:
        rows=[]
        for i in range(98):
            if mask>>(3+i)&1:
                guid=cursor.guid();_guid(guid,item=True,zero=True);rows.append([i,guid])
        if rows:result['container_slots_delta']=rows
    return result


def read_values(blob, fragments, own_guid):
    from .update_object import _Bits, _UPDATEABLE, _INDIRECT, _CG_OBJECT
    c=_Bits(blob)
    c.u8()
    if c.u8():raise ValueError('unreviewed item fragment changes')
    bits=sum(1+(f in _INDIRECT) for f in fragments if f in _UPDATEABLE)
    changes=c.take((bits+7)//8)
    first=next((f for f in fragments if f in _UPDATEABLE),None)
    if first!=_CG_OBJECT or not changes or changes[0]&3!=3:
        raise ValueError('unreviewed item fragment order')
    kinds=c.u32()
    if not kinds or kinds&~7:raise ValueError('unreviewed item data types')
    result={}
    if kinds&1:
        c.reset();mask=c.bits(4);c.reset()
        if mask&0xe and not mask&1:raise ValueError('unrooted object mask')
        if mask&1:
            if mask&2:
                entry=c.i32()
                if entry<=0:raise ValueError('invalid item entry')
                result['item_id']=entry
            if mask&4:c.take(4)
            if mask&8:c.take(4)
    if kinds&2:
        result.update(_item(c,own_guid))
        if result.get('foreign_owner'):return result
    if kinds&4:result.update(_container(c))
    if c.offset!=len(blob):raise ValueError('unreviewed item tail')
    return result


def read_root_slots(cursor):
    """Read changed ActivePlayerData InvSlots without guessing other fields."""
    mask=_mask(cursor,13)
    roots=sum(1<<i for i in range(164,269))
    if mask&roots and not mask>>163&1:
        raise ValueError('unrooted inventory slot mask')
    if not mask&roots:
        return []  # unrelated ActivePlayerData does not change InvSlots
    supported=1 | 1<<163 | roots  # block 0 with no changed children has no payload
    if mask&~supported:
        raise ValueError('unreviewed active fields precede changed inventory slots')
    result=[]
    for i in range(105):
        if mask>>(164+i)&1:
            guid=cursor.guid();_guid(guid,item=True,zero=True);result.append([i,guid])
    if cursor.offset!=len(cursor.data):raise ValueError('unreviewed inventory slot tail')
    return result
