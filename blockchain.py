import json
import hashlib
import time
from typing import List, Dict, Optional
import os

class Block:
    def __init__(self, index: int, timestamp: float, transactions: List[Dict], 
                 previous_hash: str, nonce: int = 0):
        self.index = index
        self.timestamp = timestamp
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash = self.calculate_hash()
    
    def calculate_hash(self) -> str:
        """Calculate SHA-256 hash of the block"""
        block_string = json.dumps({
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce
        }, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()
    
    def mine_block(self, difficulty: int) -> None:
        """Mine block using Proof of Work"""
        target = "0" * difficulty
        print(f"Mining block {self.index}...")
        
        while self.hash[:difficulty] != target:
            self.nonce += 1
            self.hash = self.calculate_hash()
            
            if self.nonce % 10000 == 0:
                print(f"Nonce: {self.nonce}, Hash: {self.hash[:20]}...")
        
        print(f"Block mined: {self.hash}")
    
    def to_dict(self) -> Dict:
        """Convert block to dictionary for JSON serialization"""
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "hash": self.hash
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Block':
        """Create block from dictionary"""
        block = cls(
            data["index"],
            data["timestamp"],
            data["transactions"],
            data["previous_hash"],
            data["nonce"]
        )
        block.hash = data["hash"]
        return block

class Blockchain:
    def __init__(self, difficulty: int = 4, mining_reward: float = 10.0):
        self.chain: List[Block] = []
        self.difficulty = difficulty
        self.mining_reward = mining_reward
        self.mempool: List[Dict] = []  # Unconfirmed transactions
        self.data_dir = "data"
        self.blockchain_file = os.path.join(self.data_dir, "blockchain.json")
        
        # Create data directory if it doesn't exist
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Load existing blockchain or create genesis block
        self.load_blockchain()
    
    def create_genesis_block(self) -> Block:
        """Create the first block in the blockchain"""
        genesis_transactions = [{
            "sender": "genesis",
            "recipient": "genesis",
            "amount": 0,
            "timestamp": time.time(),
            "signature": "genesis_signature"
        }]
        
        genesis_block = Block(0, time.time(), genesis_transactions, "0")
        genesis_block.mine_block(self.difficulty)
        return genesis_block
    
    def get_latest_block(self) -> Block:
        """Get the most recent block in the chain"""
        return self.chain[-1]
    
    def add_transaction_to_mempool(self, transaction: Dict) -> bool:
        """Add a transaction to the mempool (only user transactions, not mining rewards)"""
        required_fields = ["sender", "recipient", "amount", "timestamp", "signature"]
        if not all(field in transaction for field in required_fields):
            return False
        # Prevent system/mining reward transactions from being added by users
        if transaction.get("sender") in ["system", "genesis"]:
            return False
        self.mempool.append(transaction)
        return True
    
    def get_pending_transactions(self, limit: int = 10) -> List[Dict]:
        """Get transactions from mempool for mining"""
        return self.mempool[:limit]
    
    def mine_pending_transactions(self, mining_reward_address: str) -> Block:
        """Mine a new block with pending transactions (only mining reward is created by system)"""
        transactions = self.get_pending_transactions()
        # Only add mining reward transaction here
        reward_transaction = {
            "sender": "system",
            "recipient": mining_reward_address,
            "amount": self.mining_reward,
            "timestamp": time.time(),
            "signature": "mining_reward"
        }
        transactions.append(reward_transaction)

        # Remove mined transactions from mempool
        self.mempool = self.mempool[len(transactions)-1:]  # Remove mined transactions

        # Create new block
        new_block = Block(
            len(self.chain),
            time.time(),
            transactions,
            self.get_latest_block().hash
        )

        # Mine the block
        new_block.mine_block(self.difficulty)

        # Add to chain
        self.chain.append(new_block)

        # Save blockchain
        self.save_blockchain()

        # Remove all transactions that were mined (including user transactions)
        mined_tx_count = len(transactions)
        self.mempool = self.mempool[mined_tx_count-1:] if mined_tx_count > 0 else self.mempool

        return new_block
    
    def get_balance(self, address: str) -> float:
        """Calculate balance for a given address"""
        balance = 0.0
        
        for block in self.chain:
            for transaction in block.transactions:
                if transaction["recipient"] == address:
                    balance += transaction["amount"]
                if transaction["sender"] == address:
                    balance -= transaction["amount"]
        
        return balance
    
    def is_chain_valid(self) -> bool:
        """Validate the entire blockchain"""
        for i in range(1, len(self.chain)):
            current_block = self.chain[i]
            previous_block = self.chain[i-1]
            
            # Check if current block's hash is valid
            if current_block.hash != current_block.calculate_hash():
                return False
            
            # Check if previous hash matches
            if current_block.previous_hash != previous_block.hash:
                return False
            
            # Check proof of work
            if current_block.hash[:self.difficulty] != "0" * self.difficulty:
                return False
        
        return True
    
    def replace_chain(self, new_chain: List[Dict]) -> bool:
        """Replace current chain if new chain is longer and valid"""
        if len(new_chain) <= len(self.chain):
            return False
        
        # Convert dict chain to Block objects
        new_blockchain = []
        for block_data in new_chain:
            new_blockchain.append(Block.from_dict(block_data))
        
        # Create temporary blockchain to validate
        temp_blockchain = Blockchain(self.difficulty, self.mining_reward)
        temp_blockchain.chain = new_blockchain
        
        if temp_blockchain.is_chain_valid():
            self.chain = new_blockchain
            self.save_blockchain()
            return True
        
        return False
    
    def save_blockchain(self) -> None:
        """Save blockchain to JSON file"""
        chain_data = [block.to_dict() for block in self.chain]
        
        with open(self.blockchain_file, 'w') as f:
            json.dump({
                "chain": chain_data,
                "difficulty": self.difficulty,
                "mining_reward": self.mining_reward,
                "mempool": self.mempool
            }, f, indent=2)
    
    def load_blockchain(self) -> None:
        """Load blockchain from JSON file"""
        if os.path.exists(self.blockchain_file):
            try:
                with open(self.blockchain_file, 'r') as f:
                    data = json.load(f)
                
                # Load chain
                for block_data in data["chain"]:
                    self.chain.append(Block.from_dict(block_data))
                
                # Load other data
                self.difficulty = data.get("difficulty", self.difficulty)
                self.mining_reward = data.get("mining_reward", self.mining_reward)
                self.mempool = data.get("mempool", [])
                
                print(f"Loaded blockchain with {len(self.chain)} blocks")
                
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Error loading blockchain: {e}")
                self.chain = [self.create_genesis_block()]
        else:
            # Create genesis block
            self.chain = [self.create_genesis_block()]
            self.save_blockchain()
    
    def to_dict(self) -> Dict:
        """Convert blockchain to dictionary for JSON serialization"""
        return {
            "chain": [block.to_dict() for block in self.chain],
            "length": len(self.chain),
            "difficulty": self.difficulty,
            "mining_reward": self.mining_reward,
            "mempool_size": len(self.mempool)
        }

if __name__ == "__main__":
    # Test the blockchain
    blockchain = Blockchain(difficulty=3)
    
    # Add some test transactions
    test_tx1 = {
        "sender": "Alice",
        "recipient": "Bob",
        "amount": 5.0,
        "timestamp": time.time(),
        "signature": "test_signature_1"
    }
    
    test_tx2 = {
        "sender": "Bob",
        "recipient": "Charlie",
        "amount": 2.0,
        "timestamp": time.time(),
        "signature": "test_signature_2"
    }
    
    blockchain.add_transaction_to_mempool(test_tx1)
    blockchain.add_transaction_to_mempool(test_tx2)
    
    print(f"Mempool size: {len(blockchain.mempool)}")
    
    # Mine a block
    print("Mining block...")
    new_block = blockchain.mine_pending_transactions("Miner1")
    
    print(f"Blockchain length: {len(blockchain.chain)}")
    print(f"Miner1 balance: {blockchain.get_balance('Miner1')}")
    print(f"Chain valid: {blockchain.is_chain_valid()}")