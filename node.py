from flask import Flask, request, jsonify, render_template_string, redirect, url_for, flash, session
import json
import threading
import time
from typing import Dict, List
import argparse
import requests
from blockchain import Blockchain
from wallet import WalletManager, create_signed_transaction, verify_transaction_signature
from transaction import TransactionPool, TransactionValidator
import os

class BlockchainNode:
    def __init__(self, host: str = "127.0.0.1", port: int = 5000):
        self.app = Flask(__name__)
        self.app.secret_key = "supersecretkey"  # <-- Add this line
        self.host = host
        self.port = port
        
        # Initialize blockchain components
        self.blockchain = Blockchain(difficulty=4, mining_reward=10.0)
        self.wallet_manager = WalletManager()
        self.transaction_pool = TransactionPool(self.blockchain)
        self.validator = TransactionValidator(self.blockchain)
        
        # P2P network
        self.peers: List[str] = []
        self.node_id = f"{host}:{port}"
        
        # Mining status
        self.is_mining = False
        self.mining_address = None
        
        # Setup routes
        self._setup_routes()
        self._setup_ui_routes()

        print(f"Blockchain Node initialized on {self.node_id}")
        print(f"Genesis block hash: {self.blockchain.chain[0].hash}")
    
    def _setup_routes(self):
        """Setup Flask routes"""
        
        # Blockchain endpoints
        self.app.route('/chain', methods=['GET'])(self.get_chain)
        self.app.route('/mine', methods=['POST'])(self.mine_block)
        self.app.route('/transactions', methods=['POST'])(self.add_transaction)
        self.app.route('/transactions', methods=['GET'])(self.get_transactions)
        self.app.route('/balance/<address>', methods=['GET'])(self.get_balance)
        
        # Wallet endpoints
        self.app.route('/wallet/new', methods=['GET'])(self.create_wallet)
        self.app.route('/wallet/<wallet_name>', methods=['GET'])(self.get_wallet)
        self.app.route('/wallet/list', methods=['GET'])(self.list_wallets)
        self.app.route('/wallet/send', methods=['POST'])(self.send_transaction)
        
        # P2P network endpoints
        self.app.route('/peers', methods=['GET'])(self.get_peers)
        self.app.route('/peers', methods=['POST'])(self.add_peer)
        self.app.route('/sync', methods=['GET'])(self.sync_blockchain)
        
        # Node status endpoints
        self.app.route('/status', methods=['GET'])(self.get_node_status)
        self.app.route('/mempool', methods=['GET'])(self.get_mempool)
        
        @self.app.route('/', methods=['GET'])
        def home():
            # Redirect to UI index at /ui
            return redirect(url_for('ui_index'))

        @self.app.route('/docs', methods=['GET'])
        def docs():
            return jsonify({
                "info": "Logsy Blockchain Node API Documentation",
                "endpoints": {
                    "/wallet/new": "Create a new wallet (GET, ?name=yourname)",
                    "/wallet/list": "List all wallets (GET)",
                    "/wallet/<wallet_name>": "Get wallet info (GET)",
                    "/balance/<address>": "Get balance for address (GET)",
                    "/wallet/send": {
                        "method": "POST",
                        "description": "Send coins from wallet",
                        "body": {
                            "wallet_name": "string",
                            "recipient": "address",
                            "amount": "float"
                        }
                    },
                    "/mine": {
                        "method": "POST",
                        "description": "Mine a block and get reward",
                        "body": {
                            "miner_address": "address"
                        }
                    },
                    "/chain": "Get full blockchain (GET)",
                    "/transactions": {
                        "method": "GET/POST",
                        "description": "View or add raw transactions"
                    },
                    "/mempool": "Get transaction pool status (GET)",
                    "/status": "Get node status (GET)"
                },
                "usage_examples": {
                    "create_wallet": "curl 'http://localhost:5000/wallet/new?name=alice'",
                    "send_coins": "curl -X POST -H 'Content-Type: application/json' -d '{\"wallet_name\":\"alice\",\"recipient\":\"<address>\",\"amount\":5}' http://localhost:5000/wallet/send",
                    "mine_block": "curl -X POST -H 'Content-Type: application/json' -d '{\"miner_address\":\"<address>\"}' http://localhost:5000/mine",
                    "check_balance": "curl 'http://localhost:5000/balance/<address>'"
                }
            }), 200
    
    # Blockchain API endpoints
    def get_chain(self):
        """GET /chain - Return the full blockchain"""
        try:
            response = {
                'chain': [block.to_dict() for block in self.blockchain.chain],
                'length': len(self.blockchain.chain),
                'valid': self.blockchain.is_chain_valid()
            }
            return jsonify(response), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def mine_block(self):
        """POST /mine - Mine a new block"""
        try:
            data = request.get_json() or {}
            miner_address = data.get('miner_address')
            
            if not miner_address:
                return jsonify({'error': 'miner_address is required'}), 400
            
            # Check if already mining
            if self.is_mining:
                return jsonify({'error': 'Already mining a block'}), 409
            
            # Start mining in background thread
            mining_thread = threading.Thread(
                target=self._mine_block_background, 
                args=(miner_address,)
            )
            mining_thread.start()
            
            return jsonify({
                'message': 'Mining started',
                'miner_address': miner_address,
                'pending_transactions': len(self.blockchain.mempool)
            }), 202
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def _mine_block_background(self, miner_address: str):
        """Background mining process"""
        self.is_mining = True
        self.mining_address = miner_address
        
        try:
            # Add transactions from pool to blockchain mempool
            transactions_to_mine = self.transaction_pool.get_transactions_for_mining(10)
            self.blockchain.mempool.extend(transactions_to_mine)
            
            # Mine the block
            new_block = self.blockchain.mine_pending_transactions(miner_address)
            
            # Remove mined transactions from pool
            mined_tx_ids = [tx.get('transaction_id', '') for tx in new_block.transactions]
            self.transaction_pool.remove_transactions(mined_tx_ids)
            
            # Broadcast new block to peers
            self._broadcast_block(new_block)
            
            print(f"Block {new_block.index} mined successfully by {miner_address}")
            
        except Exception as e:
            print(f"Mining error: {e}")
        finally:
            self.is_mining = False
            self.mining_address = None
    
    def add_transaction(self):
        """POST /transactions - Add a new transaction (must be signed by sender)"""
        try:
            transaction_data = request.get_json()
            if not transaction_data:
                return jsonify({'error': 'Transaction data required'}), 400

            # Only allow user-initiated transactions (not mining rewards/system)
            if transaction_data.get('sender') in ['system', 'genesis']:
                return jsonify({'error': 'Cannot submit system transactions'}), 400

            # Validate and add transaction to pool
            success, message = self.transaction_pool.add_transaction(transaction_data)
            if success:
                # Broadcast transaction to peers
                self._broadcast_transaction(transaction_data)
                return jsonify({
                    'message': message,
                    'transaction_id': transaction_data.get('transaction_id'),
                    'status': 'pending'
                }), 201
            else:
                return jsonify({'error': message}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def send_transaction(self):
        """POST /wallet/send - Send coins from one wallet to another (signed)"""
        try:
            data = request.get_json()
            sender_wallet_name = data.get('wallet_name')
            recipient_address = data.get('recipient')
            amount = data.get('amount')

            if not sender_wallet_name or not recipient_address or not amount:
                return jsonify({'error': 'wallet_name, recipient, and amount required'}), 400

            wallet = self.wallet_manager.load_wallet(sender_wallet_name)
            if not wallet:
                return jsonify({'error': 'Wallet not found'}), 404

            # Create signed transaction
            from wallet import create_signed_transaction
            transaction = create_signed_transaction(wallet, recipient_address, amount)

            # Add transaction to pool
            success, message = self.transaction_pool.add_transaction(transaction)
            if success:
                self._broadcast_transaction(transaction)
                return jsonify({
                    'message': message,
                    'transaction_id': transaction.get('transaction_id'),
                    'status': 'pending'
                }), 201
            else:
                return jsonify({'error': message}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_transactions(self):
        """GET /transactions - Get pending transactions"""
        try:
            transactions = self.transaction_pool.pending_transactions
            return jsonify({
                'transactions': transactions,
                'count': len(transactions)
            }, 200)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_balance(self, address: str):
        """GET /balance/<address> - Get wallet balance"""
        try:
            balance = self.blockchain.get_balance(address)
            return jsonify({
                'address': address,
                'balance': balance
            }), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # Wallet API endpoints
    def create_wallet(self):
        """GET /wallet/new - Create a new wallet"""
        try:
            wallet_name = request.args.get('name')
            wallet = self.wallet_manager.create_wallet(wallet_name)
            
            return jsonify({
                'message': 'Wallet created successfully',
                'address': wallet.address,
                'public_key': wallet.get_public_key_hex()
            }), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_wallet(self, wallet_name: str):
        """GET /wallet/<wallet_name> - Get wallet information"""
        try:
            wallet = self.wallet_manager.load_wallet(wallet_name)
            
            if not wallet:
                return jsonify({'error': 'Wallet not found'}), 404
            
            balance = self.blockchain.get_balance(wallet.address)
            
            return jsonify({
                'name': wallet_name,
                'address': wallet.address,
                'public_key': wallet.get_public_key_hex(),
                'balance': balance
            }), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def list_wallets(self):
        """GET /wallet/list - List all wallets"""
        try:
            wallets = self.wallet_manager.list_wallets()
            wallet_info = []
            
            for wallet_name in wallets:
                wallet = self.wallet_manager.load_wallet(wallet_name)
                if wallet:
                    balance = self.blockchain.get_balance(wallet.address)
                    wallet_info.append({
                        'name': wallet_name,
                        'address': wallet.address,
                        'balance': balance
                    })
            
            return jsonify({
                'wallets': wallet_info,
                'count': len(wallet_info)
            }), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # P2P Network endpoints
    def get_peers(self):
        """GET /peers - Get list of peer nodes"""
        return jsonify({
            'peers': self.peers,
            'count': len(self.peers)
        }), 200
    
    def add_peer(self):
        """POST /peers - Add a new peer node"""
        try:
            data = request.get_json()
            peer_address = data.get('address')
            
            if not peer_address:
                return jsonify({'error': 'Peer address required'}), 400
            
            if peer_address not in self.peers and peer_address != self.node_id:
                self.peers.append(peer_address)
                return jsonify({
                    'message': 'Peer added successfully',
                    'peer': peer_address
                }), 201
            else:
                return jsonify({'message': 'Peer already exists'}), 200
                
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def sync_blockchain(self):
        """GET /sync - Sync blockchain with peers"""
        try:
            synced_count = 0
            longest_chain = self.blockchain.chain
            
            for peer in self.peers:
                try:
                    response = requests.get(f"http://{peer}/chain", timeout=5)
                    if response.status_code == 200:
                        peer_data = response.json()
                        peer_chain = peer_data['chain']
                        
                        if len(peer_chain) > len(longest_chain):
                            if self.blockchain.replace_chain(peer_chain):
                                longest_chain = peer_chain
                                synced_count += 1
                                print(f"Blockchain updated from peer: {peer}")
                
                except requests.RequestException as e:
                    print(f"Failed to sync with peer {peer}: {e}")
            
            return jsonify({
                'message': 'Sync completed',
                'synced_peers': synced_count,
                'blockchain_length': len(self.blockchain.chain)
            }), 200
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # Status endpoints
    def get_node_status(self):
        """GET /status - Get node status information"""
        return jsonify({
            'node_id': self.node_id,
            'blockchain_length': len(self.blockchain.chain),
            'pending_transactions': len(self.blockchain.mempool),
            'transaction_pool_size': len(self.transaction_pool.pending_transactions),
            'peers_count': len(self.peers),
            'peers': self.peers,
            'is_mining': self.is_mining,
            'mining_address': self.mining_address,
            'difficulty': self.blockchain.difficulty,
            'mining_reward': self.blockchain.mining_reward
        }), 200
    
    def get_mempool(self):
        """GET /mempool - Get transaction pool status"""
        return jsonify(self.transaction_pool.get_pool_stats()), 200
    
    # P2P Broadcasting methods
    def _broadcast_block(self, block):
        """Broadcast new block to all peers"""
        block_data = block.to_dict()
        
        for peer in self.peers:
            try:
                requests.post(
                    f"http://{peer}/blocks/receive",
                    json=block_data,
                    timeout=5
                )
            except requests.RequestException as e:
                print(f"Failed to broadcast block to {peer}: {e}")
    
    def _broadcast_transaction(self, transaction):
        """Broadcast new transaction to all peers"""
        for peer in self.peers:
            try:
                requests.post(
                    f"http://{peer}/transactions",
                    json=transaction,
                    timeout=5
                )
            except requests.RequestException as e:
                print(f"Failed to broadcast transaction to {peer}: {e}")
    
    def run(self, debug: bool = False):
        """Start the Flask server"""
        print(f"Starting blockchain node on {self.host}:{self.port}")
        self.app.run(host=self.host, port=self.port, debug=debug, threaded=True)

    def _setup_ui_routes(self):
        """Setup HTML UI routes"""
        HTML_TEMPLATE_LOGIN = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Logsy Wallet Login</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .container { max-width: 400px; margin: auto; }
                .msg { color: green; }
                .error { color: red; }
            </style>
        </head>
        <body>
        <div class="container">
            <h2>Login to Logsy Wallet</h2>
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="{{ category }}">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            <form method="post" action="{{ url_for('ui_login') }}">
                <label>Wallet Name:</label>
                <input type="text" name="wallet_name" required>
                <button type="submit">Login</button>
            </form>
            <hr>
            <form method="post" action="{{ url_for('ui_create_wallet') }}">
                <label>Create New Wallet:</label>
                <input type="text" name="wallet_name" placeholder="Wallet name (optional)">
                <button type="submit">Create Wallet</button>
            </form>
        </div>
        </body>
        </html>
        """

        HTML_TEMPLATE_MAIN = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Logsy Wallet Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .container { max-width: 700px; margin: auto; }
                h2 { margin-top: 40px; }
                form { margin-bottom: 20px; }
                input, select, textarea { margin: 5px 0; padding: 6px; width: 100%; }
                .msg { color: green; }
                .error { color: red; }
                .logout { float: right; }
            </style>
        </head>
        <body>
        <div class="container">
            <form method="post" action="{{ url_for('ui_logout') }}">
                <button class="logout" type="submit">Logout</button>
            </form>
            <h1>Welcome, {{ wallet_name }}</h1>
            <h3>Wallet Info</h3>
            <b>Address:</b> {{ wallet.address }}<br>
            <b>Balance:</b> {{ balance }}<br>
            <b>Public Key:</b> <small>{{ wallet.get_public_key_hex() }}</small>
            <hr>
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="{{ category }}">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}

            <h2>Buy Coins</h2>
            <form method="post" action="{{ url_for('ui_buy_coins') }}">
                <label>Current Coin Value (Mining Reward):</label>
                <input type="text" value="{{ mining_reward }}" readonly>
                <label>Amount to Buy:</label>
                <input type="number" step="any" name="buy_amount" required>
                <button type="submit">Buy</button>
            </form>

            <h2>Check Balance</h2>
            <form method="post" action="{{ url_for('ui_check_balance') }}">
                <button type="submit">Refresh Balance</button>
            </form>

            <h2>Create Transaction</h2>
            <form method="post" action="{{ url_for('ui_create_transaction') }}">
                <label>Recipient Address:</label>
                <input type="text" name="recipient_address" required>
                <label>Amount:</label>
                <input type="number" step="any" name="amount" required>
                <button type="submit">Send</button>
            </form>
            {% if transaction %}
                <h3>Transaction Created</h3>
                <pre>{{ transaction }}</pre>
            {% endif %}

            <h2>Verify Transaction Signature</h2>
            <form method="post" action="{{ url_for('ui_verify_signature') }}">
                <label>Transaction (JSON):</label>
                <textarea name="transaction_json" rows="6" required></textarea>
                <label>Public Key (hex):</label>
                <input type="text" name="public_key_hex" required>
                <button type="submit">Verify Signature</button>
            </form>
            {% if signature_result is not none %}
                <div class="msg">Signature valid: {{ signature_result }}</div>
            {% endif %}

            <h2>Delete Wallet</h2>
            <form method="post" action="{{ url_for('ui_delete_wallet') }}">
                <button type="submit" onclick="return confirm('Delete wallet {{ wallet_name }}?')">Delete Wallet</button>
            </form>
        </div>
        </body>
        </html>
        """

        @self.app.route("/ui", methods=["GET", "POST"])
        def ui_index():
            wallet_name = session.get("wallet_name")
            if not wallet_name:
                return render_template_string(HTML_TEMPLATE_LOGIN)
            wallet = self.wallet_manager.load_wallet(wallet_name)
            if not wallet:
                flash("Wallet not found. Please login again.", "error")
                session.pop("wallet_name", None)
                return redirect(url_for("ui_index"))
            balance = self.blockchain.get_balance(wallet.address)
            transaction = session.pop("transaction", None)
            signature_result = session.pop("signature_result", None)
            mining_reward = self.blockchain.mining_reward
            return render_template_string(
                HTML_TEMPLATE_MAIN,
                wallet_name=wallet_name,
                wallet=wallet,
                balance=balance,
                transaction=transaction,
                signature_result=signature_result,
                mining_reward=mining_reward
            )

        @self.app.route("/login", methods=["POST"])
        def ui_login():
            wallet_name = request.form.get("wallet_name")
            wallet = self.wallet_manager.load_wallet(wallet_name)
            if wallet:
                session["wallet_name"] = wallet_name
                return redirect(url_for("ui_index"))
            else:
                flash("Wallet not found. Please create or try again.", "error")
                return redirect(url_for("ui_index"))

        @self.app.route("/logout", methods=["POST"])
        def ui_logout():
            session.pop("wallet_name", None)
            return redirect(url_for("ui_index"))

        @self.app.route("/create_wallet", methods=["POST"])
        def ui_create_wallet():
            wallet_name = request.form.get("wallet_name")
            wallet = self.wallet_manager.create_wallet(wallet_name if wallet_name else None)
            flash(f"Wallet '{wallet_name or wallet.address}' created!", "msg")
            session["wallet_name"] = wallet_name or wallet.address
            return redirect(url_for("ui_index"))

        @self.app.route("/delete_wallet", methods=["POST"])
        def ui_delete_wallet():
            wallet_name = session.get("wallet_name")
            if wallet_name and self.wallet_manager.delete_wallet(wallet_name):
                flash(f"Wallet '{wallet_name}' deleted.", "msg")
                session.pop("wallet_name", None)
            else:
                flash(f"Wallet '{wallet_name}' not found.", "error")
            return redirect(url_for("ui_index"))

        @self.app.route("/create_transaction", methods=["POST"])
        def ui_create_transaction():
            wallet_name = session.get("wallet_name")
            wallet = self.wallet_manager.load_wallet(wallet_name)
            if not wallet:
                flash("Wallet not found.", "error")
                return redirect(url_for("ui_index"))
            recipient_address = request.form.get("recipient_address")
            amount = float(request.form.get("amount"))
            transaction = create_signed_transaction(wallet, recipient_address, amount)
            flash("Transaction created and signed.", "msg")
            session["transaction"] = json.dumps(transaction, indent=2)
            return redirect(url_for("ui_index"))

        @self.app.route("/verify_signature", methods=["POST"])
        def ui_verify_signature():
            transaction_json = request.form.get("transaction_json")
            public_key_hex = request.form.get("public_key_hex")
            try:
                transaction = json.loads(transaction_json)
                result = verify_transaction_signature(transaction, public_key_hex)
                flash(f"Signature valid: {result}", "msg" if result else "error")
                session["signature_result"] = result
            except Exception as e:
                flash(f"Error verifying signature: {e}", "error")
                session["signature_result"] = None
            return redirect(url_for("ui_index"))

        @self.app.route("/check_balance", methods=["POST"])
        def ui_check_balance():
            # Just reload the page to refresh balance
            return redirect(url_for("ui_index"))

        @self.app.route("/buy_coins", methods=["POST"])
        def ui_buy_coins():
            wallet_name = session.get("wallet_name")
            wallet = self.wallet_manager.load_wallet(wallet_name)
            if not wallet:
                flash("Wallet not found.", "error")
                return redirect(url_for("ui_index"))
            try:
                buy_amount = float(request.form.get("buy_amount"))
                if buy_amount <= 0:
                    flash("Amount must be positive.", "error")
                    return redirect(url_for("ui_index"))
                # Simulate mining reward transaction with valid system signature
                transaction = {
                    "sender": "system",
                    "recipient": wallet.address,
                    "amount": buy_amount,
                    "timestamp": time.time(),
                    "sender_public_key": "",
                    "signature": "SYSTEM"  # <-- Add a placeholder signature for system tx
                }
                success, message = self.transaction_pool.add_transaction(transaction)
                if success:
                    flash(f"Buy order placed: {buy_amount} coins will be credited after mining.", "msg")
                else:
                    flash(f"Buy failed: {message}", "error")
            except Exception as e:
                flash(f"Error: {e}", "error")
            return redirect(url_for("ui_index"))

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Blockchain Node')
    parser.add_argument('--host', default='127.0.0.1', help='Host address')
    parser.add_argument('--port', type=int, default=5000, help='Port number')
    parser.add_argument('--peers', nargs='*', help='Initial peer addresses')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    # Create and configure node
    node = BlockchainNode(args.host, args.port)
    
    # Add initial peers
    if args.peers:
        node.peers.extend(args.peers)
        print(f"Added initial peers: {args.peers}")
    
    # Start the node
    try:
        node.run(debug=True)  # <-- Force debug mode ON
    except KeyboardInterrupt:
        print("\nShutting down blockchain node...")

if __name__ == '__main__':
    main()