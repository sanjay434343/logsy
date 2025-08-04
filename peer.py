import socket
import json
import threading
import time
import requests
from typing import List, Dict, Optional, Callable
import queue
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class P2PMessage:
    """P2P message structure"""
    def __init__(self, message_type: str, data: Dict, sender_id: str):
        self.type = message_type
        self.data = data
        self.sender_id = sender_id
        self.timestamp = time.time()
    
    def to_dict(self) -> Dict:
        return {
            'type': self.type,
            'data': self.data,
            'sender_id': self.sender_id,
            'timestamp': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'P2PMessage':
        msg = cls(data['type'], data['data'], data['sender_id'])
        msg.timestamp = data['timestamp']
        return msg
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_json(cls, json_str: str) -> 'P2PMessage':
        return cls.from_dict(json.loads(json_str))

class P2PPeer:
    """Represents a peer in the network"""
    def __init__(self, address: str, port: int, peer_id: str = None):
        self.address = address
        self.port = port
        self.peer_id = peer_id or f"{address}:{port}"
        self.last_seen = time.time()
        self.connection_attempts = 0
        self.is_connected = False
        self.socket_connection = None
    
    def to_dict(self) -> Dict:
        return {
            'address': self.address,
            'port': self.port,
            'peer_id': self.peer_id,
            'last_seen': self.last_seen,
            'is_connected': self.is_connected
        }
    
    def __str__(self):
        return f"Peer({self.peer_id})"
    
    def __repr__(self):
        return self.__str__()

class P2PNetwork:
    """P2P network manager for blockchain synchronization"""
    
    def __init__(self, host: str, port: int, node_id: str):
        self.host = host
        self.port = port
        self.node_id = node_id
        self.peers: Dict[str, P2PPeer] = {}
        self.message_handlers: Dict[str, Callable] = {}
        
        # Network components
        self.server_socket = None
        self.is_running = False
        self.message_queue = queue.Queue()
        
        # Threading
        self.server_thread = None
        self.message_processor_thread = None
        self.peer_discovery_thread = None
        
        # Message types
        self.MESSAGE_TYPES = {
            'PING': 'ping',
            'PONG': 'pong',
            'NEW_BLOCK': 'new_block',
            'NEW_TRANSACTION': 'new_transaction',
            'REQUEST_CHAIN': 'request_chain',
            'CHAIN_RESPONSE': 'chain_response',
            'PEER_DISCOVERY': 'peer_discovery',
            'PEER_LIST': 'peer_list'
        }
        
        # Setup default message handlers
        self._setup_default_handlers()
    
    def _setup_default_handlers(self):
        """Setup default message handlers"""
        self.register_handler(self.MESSAGE_TYPES['PING'], self._handle_ping)
        self.register_handler(self.MESSAGE_TYPES['PONG'], self._handle_pong)
        self.register_handler(self.MESSAGE_TYPES['PEER_DISCOVERY'], self._handle_peer_discovery)
        self.register_handler(self.MESSAGE_TYPES['PEER_LIST'], self._handle_peer_list)
    
    def register_handler(self, message_type: str, handler: Callable):
        """Register a message handler"""
        self.message_handlers[message_type] = handler
    
    def start(self):
        """Start the P2P network"""
        logger.info(f"Starting P2P network on {self.host}:{self.port}")
        
        self.is_running = True
        
        # Start server socket
        self._start_server()
        
        # Start message processor
        self.message_processor_thread = threading.Thread(target=self._process_messages)
        self.message_processor_thread.daemon = True
        self.message_processor_thread.start()
        
        # Start peer discovery
        self.peer_discovery_thread = threading.Thread(target=self._peer_discovery_loop)
        self.peer_discovery_thread.daemon = True
        self.peer_discovery_thread.start()
        
        logger.info("P2P network started successfully")
    
    def stop(self):
        """Stop the P2P network"""
        logger.info("Stopping P2P network...")
        
        self.is_running = False
        
        # Close server socket
        if self.server_socket:
            self.server_socket.close()
        
        # Close peer connections
        for peer in self.peers.values():
            if peer.socket_connection:
                peer.socket_connection.close()
        
        logger.info("P2P network stopped")
    
    def _start_server(self):
        """Start the server socket"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(10)
            
            # Start server thread
            self.server_thread = threading.Thread(target=self._accept_connections)
            self.server_thread.daemon = True
            self.server_thread.start()
            
        except Exception as e:
            logger.error(f"Failed to start P2P server: {e}")
            raise
    
    def _accept_connections(self):
        """Accept incoming peer connections"""
        while self.is_running:
            try:
                client_socket, addr = self.server_socket.accept()
                logger.info(f"New peer connection from {addr}")
                
                # Handle peer connection in separate thread
                peer_thread = threading.Thread(
                    target=self._handle_peer_connection,
                    args=(client_socket, addr)
                )
                peer_thread.daemon = True
                peer_thread.start()
                
            except Exception as e:
                if self.is_running:
                    logger.error(f"Error accepting connection: {e}")
    
    def _handle_peer_connection(self, client_socket: socket.socket, addr):
        """Handle individual peer connection"""
        peer_id = f"{addr[0]}:{addr[1]}"
        
        try:
            while self.is_running:
                # Receive message
                data = client_socket.recv(4096)
                if not data:
                    break
                
                try:
                    message = P2PMessage.from_json(data.decode())
                    self.message_queue.put(message)
                    logger.debug(f"Received message from {peer_id}: {message.type}")
                    
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from {peer_id}")
                    
        except Exception as e:
            logger.error(f"Error handling peer {peer_id}: {e}")
        finally:
            client_socket.close()
            if peer_id in self.peers:
                self.peers[peer_id].is_connected = False
    
    def _process_messages(self):
        """Process incoming messages"""
        while self.is_running:
            try:
                message = self.message_queue.get(timeout=1)
                
                # Handle message
                if message.type in self.message_handlers:
                    self.message_handlers[message.type](message)
                else:
                    logger.warning(f"No handler for message type: {message.type}")
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing message: {e}")
    
    def _peer_discovery_loop(self):
        """Periodic peer discovery and maintenance"""
        while self.is_running:
            try:
                # Ping all peers
                self._ping_all_peers()
                
                # Clean up dead peers
                self._cleanup_dead_peers()
                
                # Sleep for 30 seconds
                time.sleep(30)
                
            except Exception as e:
                logger.error(f"Error in peer discovery: {e}")
    
    def add_peer(self, address: str, port: int) -> bool:
        """Add a new peer to the network"""
        peer_id = f"{address}:{port}"
        
        if peer_id == self.node_id:
            return False  # Don't add self
        
        if peer_id not in self.peers:
            peer = P2PPeer(address, port)
            self.peers[peer_id] = peer
            logger.info(f"Added peer: {peer_id}")
            
            # Try to connect
            self._connect_to_peer(peer)
            
            return True
        return False
    
    def _connect_to_peer(self, peer: P2PPeer) -> bool:
        """Connect to a peer"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((peer.address, peer.port))
            
            peer.socket_connection = sock
            peer.is_connected = True
            peer.last_seen = time.time()
            peer.connection_attempts = 0
            
            logger.info(f"Connected to peer: {peer.peer_id}")
            
            # Send ping
            self._send_message_to_peer(peer, self.MESSAGE_TYPES['PING'], {})
            
            return True
            
        except Exception as e:
            peer.connection_attempts += 1
            peer.is_connected = False
            logger.warning(f"Failed to connect to {peer.peer_id}: {e}")
            return False
    
    def _send_message_to_peer(self, peer: P2PPeer, message_type: str, data: Dict) -> bool:
        """Send message to a specific peer"""
        if not peer.is_connected or not peer.socket_connection:
            return False
        
        try:
            message = P2PMessage(message_type, data, self.node_id)
            peer.socket_connection.send(message.to_json().encode())
            return True
            
        except Exception as e:
            logger.error(f"Failed to send message to {peer.peer_id}: {e}")
            peer.is_connected = False
            return False
    
    def broadcast_message(self, message_type: str, data: Dict):
        """Broadcast message to all connected peers"""
        message = P2PMessage(message_type, data, self.node_id)
        sent_count = 0
        
        for peer in self.peers.values():
            if peer.is_connected:
                if self._send_message_to_peer(peer, message_type, data):
                    sent_count += 1
        
        logger.debug(f"Broadcasted {message_type} to {sent_count} peers")
        return sent_count
    
    def _ping_all_peers(self):
        """Send ping to all peers"""
        for peer in self.peers.values():
            if peer.is_connected:
                self._send_message_to_peer(peer, self.MESSAGE_TYPES['PING'], {
                    'timestamp': time.time()
                })
            elif peer.connection_attempts < 3:
                # Try to reconnect
                self._connect_to_peer(peer)
    
    def _cleanup_dead_peers(self):
        """Remove dead peers from the network"""
        current_time = time.time()
        dead_peers = []
        
        for peer_id, peer in self.peers.items():
            if not peer.is_connected and peer.connection_attempts >= 3:
                if current_time - peer.last_seen > 300:  # 5 minutes
                    dead_peers.append(peer_id)
        
        for peer_id in dead_peers:
            del self.peers[peer_id]
            logger.info(f"Removed dead peer: {peer_id}")
    
    # Default message handlers
    def _handle_ping(self, message: P2PMessage):
        """Handle ping message"""
        # Update peer last seen
        if message.sender_id in self.peers:
            self.peers[message.sender_id].last_seen = time.time()
        
        # Send pong response
        # Note: In a real implementation, you'd send back through the same connection
        logger.debug(f"Received ping from {message.sender_id}")
    
    def _handle_pong(self, message: P2PMessage):
        """Handle pong message"""
        if message.sender_id in self.peers:
            self.peers[message.sender_id].last_seen = time.time()
        logger.debug(f"Received pong from {message.sender_id}")
    
    def _handle_peer_discovery(self, message: P2PMessage):
        """Handle peer discovery message"""
        # Send peer list response
        peer_list = [peer.to_dict() for peer in self.peers.values()]
        # In real implementation, send response back to sender
        logger.debug(f"Peer discovery request from {message.sender_id}")
    
    def _handle_peer_list(self, message: P2PMessage):
        """Handle peer list message"""
        peer_list = message.data.get('peers', [])
        
        for peer_info in peer_list:
            self.add_peer(peer_info['address'], peer_info['port'])
        
        logger.debug(f"Received peer list with {len(peer_list)} peers")
    
    def get_peer_stats(self) -> Dict:
        """Get peer network statistics"""
        connected_peers = sum(1 for p in self.peers.values() if p.is_connected)
        
        return {
            'node_id': self.node_id,
            'total_peers': len(self.peers),
            'connected_peers': connected_peers,
            'peers': [peer.to_dict() for peer in self.peers.values()]
        }

class HTTPP2PSync:
    """HTTP-based P2P synchronization (simpler alternative to socket-based)"""
    
    def __init__(self, node_url: str):
        self.node_url = node_url
        self.peers: List[str] = []
    
    def add_peer(self, peer_url: str):
        """Add peer URL"""
        if peer_url not in self.peers and peer_url != self.node_url:
            self.peers.append(peer_url)
    
    def sync_blockchain(self) -> Dict:
        """Sync blockchain with peers via HTTP"""
        sync_results = {'synced': 0, 'failed': 0, 'longest_chain': 0}
        
        for peer_url in self.peers:
            try:
                # Get peer's blockchain
                response = requests.get(f"{peer_url}/chain", timeout=10)
                if response.status_code == 200:
                    peer_data = response.json()
                    chain_length = peer_data['length']
                    
                    if chain_length > sync_results['longest_chain']:
                        # Try to update local chain
                        update_response = requests.post(
                            f"{self.node_url}/sync/update",
                            json=peer_data,
                            timeout=10
                        )
                        
                        if update_response.status_code == 200:
                            sync_results['synced'] += 1
                            sync_results['longest_chain'] = chain_length
                
            except requests.RequestException as e:
                sync_results['failed'] += 1
                logger.error(f"Failed to sync with {peer_url}: {e}")
        
        return sync_results
    
    def broadcast_transaction(self, transaction_data: Dict):
        """Broadcast transaction to all peers"""
        broadcast_results = {'sent': 0, 'failed': 0}
        
        for peer_url in self.peers:
            try:
                response = requests.post(
                    f"{peer_url}/transactions",
                    json=transaction_data,
                    timeout=5
                )
                
                if response.status_code in [200, 201]:
                    broadcast_results['sent'] += 1
                else:
                    broadcast_results['failed'] += 1
                    
            except requests.RequestException:
                broadcast_results['failed'] += 1
        
        return broadcast_results
    
    def broadcast_block(self, block_data: Dict):
        """Broadcast new block to all peers"""
        broadcast_results = {'sent': 0, 'failed': 0}
        
        for peer_url in self.peers:
            try:
                response = requests.post(
                    f"{peer_url}/blocks/new",
                    json=block_data,
                    timeout=5
                )
                
                if response.status_code in [200, 201]:
                    broadcast_results['sent'] += 1
                else:
                    broadcast_results['failed'] += 1
                    
            except requests.RequestException:
                broadcast_results['failed'] += 1
        
        return broadcast_results

if __name__ == "__main__":
    # Test P2P network
    import argparse
    
    parser = argparse.ArgumentParser(description='P2P Network Test')
    parser.add_argument('--host', default='127.0.0.1', help='Host address')
    parser.add_argument('--port', type=int, default=8000, help='P2P port')
    parser.add_argument('--peer', action='append', help='Peer addresses (host:port)')
    
    args = parser.parse_args()
    
    # Create P2P network
    node_id = f"{args.host}:{args.port}"
    p2p = P2PNetwork(args.host, args.port, node_id)