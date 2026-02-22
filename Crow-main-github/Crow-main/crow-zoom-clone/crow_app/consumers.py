# crow_app/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer

class VideoCallConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'video_call_{self.room_id}'
        self.user = self.scope['user']
        
        if not self.user.is_authenticated:
            await self.close()
            return
        
        self.user_id = str(self.user.id)
        self.username = self.user.username
        
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_left',
                'userId': self.user_id,
                'username': self.username
            }
        )
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        message_type = data.get('type')
        
        # KEY FIX: Ensure signaling data includes the sender's ID for the recipient to track
        if message_type in ['offer', 'answer', 'ice-candidate']:
            target = data.get('target')
            if target:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': f'webrtc_{message_type.replace("-", "_")}',
                        'data': data,
                        'sender': self.user_id,
                        'target': target
                    }
                )
        elif message_type == 'join':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_joined',
                    'userId': self.user_id,
                    'username': self.username,
                    'sender_channel': self.channel_name
                }
            )

    async def user_joined(self, event):
        if event['userId'] != self.user_id:
            await self.send(text_data=json.dumps({
                'type': 'user-joined',
                'userId': event['userId'],
                'username': event['username']
            }))

    async def user_left(self, event):
        await self.send(text_data=json.dumps(event))

    # Generic forwarder for WebRTC events (Offer, Answer, ICE)
    async def webrtc_offer(self, event):
        if event['target'] == self.user_id:
            await self.send(text_data=json.dumps(event['data']))

    async def webrtc_answer(self, event):
        if event['target'] == self.user_id:
            await self.send(text_data=json.dumps(event['data']))

    async def webrtc_ice_candidate(self, event):
        if event['target'] == self.user_id:
            await self.send(text_data=json.dumps(event['data']))