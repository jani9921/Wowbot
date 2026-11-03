"""Local delivery continuity, separate from server facts and input authority."""
import re


def stamp(value):
    if (not isinstance(value, dict) or set(value) != {'sender_id', 'sequence'}
            or not isinstance(value.get('sender_id'), str)
            or re.fullmatch('[a-f0-9]{32}', value['sender_id']) is None
            or type(value.get('sequence')) is not int or not 0 < value['sequence'] < 2**63):
        raise ValueError('invalid local stream stamp')
    return dict(value)


class DeliveryContinuity:
    """Caller owns the inbox lock. Loss is sticky until a new IPC context."""
    def __init__(self):
        self.loss_generation = 0
        self.last_loss = None
        self.reset()

    def reset(self):
        self.sender_id = None
        self.sequence = 0
        self.state = 'UNSEEN'
        self.retired = []

    def lost(self, reason):
        self.loss_generation += 1
        self.last_loss = reason
        self.state = 'GAP'

    def accept(self, incoming):
        if incoming is None:
            if self.sender_id is not None:
                self.lost('unsequenced_delivery')
            elif self.state == 'UNSEEN':
                self.state = 'UNSEQUENCED'
            return True  # legacy positive samples never prove continuity
        value = stamp(incoming)
        sender, sequence = value['sender_id'], value['sequence']
        if sender in self.retired:
            return False
        if sender != self.sender_id:
            if self.sender_id is not None:
                self.retired = [*self.retired[-7:], self.sender_id]
                self.lost('sender_changed')
            elif self.state == 'UNSEQUENCED':
                self.lost('delivery_protocol_changed')
            self.sender_id, self.sequence = sender, 0
        if sequence <= self.sequence:
            return False  # duplicate/out-of-order datagrams cannot rewind delivery
        if sequence != self.sequence+1:
            self.lost('sequence_gap')
        elif self.state == 'UNSEEN':
            self.state = 'CONTIGUOUS'
        self.sequence = sequence
        return True

    def snapshot(self):
        return {'state':self.state, 'sender_id':self.sender_id, 'sequence':self.sequence,
                'loss_generation':self.loss_generation, 'last_loss':self.last_loss}
