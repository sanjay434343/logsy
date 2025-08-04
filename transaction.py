import json
import time
from typing import Dict, List, Optional, Tuple
from wallet import verify_transaction_signature, Wallet

class Transaction:
    def __init__(self, sender: str, recipient: str, amount: float, 
                 timestamp: float = None, signature: str = None, 
                 sender_public_key: str = None):
        self.sender = sender
        self.recipient = recipient
        self.amount = amount
        self.timestamp = timestamp if timestamp else time.time()
        self.signature = signature
        self.sender_public_key = sender_public_key
        self.transaction_id = self.calculate_transaction_id()
    
    def calculate_transaction_id(self) -> str:
        """Calculate unique transaction ID"""
        import hashlib
        tx_string = json.dumps({
            "sender": self.sender,
            "recipient": self.recipient,
            "amount": self.amount,
            "timestamp": self.timestamp
        }, sort_keys=True)
        return hashlib.sha256(tx_string.encode()).hexdigest()
    
    def to_dict(self) -> Dict:
        """Convert transaction to dictionary"""
        return {
            "transaction_id": self.transaction_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "signature": self.signature,
            "sender_public_key": self.sender_public_key
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Transaction':
        """Create transaction from dictionary"""
        return cls(
            sender=data["sender"],
            recipient=data["recipient"],
            amount=data["amount"],
            timestamp=data["timestamp"],
            signature=data.get("signature"),
            sender_public_key=data.get("sender_public_key")
        )

class TransactionValidator:
    def __init__(self, blockchain):
        self.blockchain = blockchain

    def validate_transaction(self, transaction):
        """Validate a transaction comprehensively"""
        required_fields = ["sender", "recipient", "amount", "timestamp", "signature"]
        if not all(field in transaction for field in required_fields):
            return False, "Missing required transaction fields"
        if transaction["amount"] <= 0:
            return False, "Transaction amount must be positive"
        if transaction["sender"] == transaction["recipient"]:
            return False, "Sender and recipient cannot be the same"
        # Only allow system/mining reward transactions to be created by system
        if transaction["sender"] in ["system", "genesis"]:
            # Only allow if signature is correct
            if transaction.get("signature") not in ["mining_reward", "genesis_signature"]:
                return False, "Invalid system transaction signature"
            return True, "System transaction"
        # Accept system transactions with signature "SYSTEM", "mining_reward", or "genesis_signature"
        if transaction.get("sender") == "system":
            if transaction.get("signature") in ["SYSTEM", "mining_reward", "genesis_signature"]:
                return True, "System transaction valid"
            # Accept empty signature for system transactions (if needed)
            if transaction.get("signature") == "":
                return True, "System transaction valid"
            return False, "Invalid system transaction signature"
        if not self._check_sufficient_balance(transaction):
            return False, "Insufficient balance"
        if not self._validate_signature(transaction):
            return False, "Invalid transaction signature"
        if self._check_double_spending(transaction):
            return False, "Double spending detected"
        return True, "Transaction valid"
    
    def _check_sufficient_balance(self, transaction: Dict) -> bool:
        """Check if sender has sufficient balance"""
        sender_balance = self.blockchain.get_balance(transaction["sender"])
        return sender_balance >= transaction["amount"]
    
    def _validate_signature(self, transaction: Dict) -> bool:
        """Validate transaction signature"""
        if "sender_public_key" not in transaction:
            return False
        
        return verify_transaction_signature(
            transaction, 
            transaction["sender_public_key"]
        )
    
    def _check_double_spending(self, transaction: Dict) -> bool:
        """Check for potential double spending"""
        # Simple double spending check - look for duplicate transactions
        tx_id = Transaction.from_dict(transaction).transaction_id
        
        # Check in confirmed transactions (blockchain)
        for block in self.blockchain.chain:
            for tx in block.transactions:
                if tx.get("transaction_id") == tx_id:
                    return True
        
        # Check in mempool
        for tx in self.blockchain.mempool:
            existing_tx = Transaction.from_dict(tx)
            if existing_tx.transaction_id == tx_id:
                return True
        
        return False

class TransactionPool:
    def __init__(self, blockchain, max_pool_size: int = 1000):
        self.blockchain = blockchain
        self.validator = TransactionValidator(blockchain)
        self.max_pool_size = max_pool_size
        self.pending_transactions: List[Dict] = []
    
    def add_transaction(self, transaction: Dict) -> Tuple[bool, str]:
        """Add transaction to the pool after validation"""
        
        # Validate transaction
        is_valid, message = self.validator.validate_transaction(transaction)
        if not is_valid:
            return False, message
        
        # Check pool size limit
        if len(self.pending_transactions) >= self.max_pool_size:
            return False, "Transaction pool is full"
        
        # Add transaction ID if not present
        if "transaction_id" not in transaction:
            tx_obj = Transaction.from_dict(transaction)
            transaction["transaction_id"] = tx_obj.transaction_id
        
        # Add to pending transactions
        self.pending_transactions.append(transaction)
        
        return True, "Transaction added to pool"
    
    def get_transactions_for_mining(self, max_transactions: int = 10) -> List[Dict]:
        """Get transactions for mining (highest fee first)"""
        # For simplicity, return transactions in FIFO order
        # In a real implementation, you'd prioritize by fee
        return self.pending_transactions[:max_transactions]
    
    def remove_transactions(self, transaction_ids: List[str]) -> None:
        """Remove transactions from pool (after mining)"""
        self.pending_transactions = [
            tx for tx in self.pending_transactions 
            if tx.get("transaction_id") not in transaction_ids
        ]
    
    def get_transaction_by_id(self, transaction_id: str) -> Optional[Dict]:
        """Get transaction by ID"""
        for tx in self.pending_transactions:
            if tx.get("transaction_id") == transaction_id:
                return tx
        return None
    
    def get_transactions_by_address(self, address: str) -> List[Dict]:
        """Get all transactions involving an address"""
        transactions = []
        for tx in self.pending_transactions:
            if tx["sender"] == address or tx["recipient"] == address:
                transactions.append(tx)
        return transactions
    
    def clear_invalid_transactions(self) -> int:
        """Remove invalid transactions from pool"""
        valid_transactions = []
        removed_count = 0
        
        for tx in self.pending_transactions:
            is_valid, _ = self.validator.validate_transaction(tx)
            if is_valid:
                valid_transactions.append(tx)
            else:
                removed_count += 1
        
        self.pending_transactions = valid_transactions
        return removed_count
    
    def get_pool_stats(self) -> Dict:
        """Get transaction pool statistics"""
        return {
            "total_transactions": len(self.pending_transactions),
            "max_pool_size": self.max_pool_size,
            "pool_usage": f"{len(self.pending_transactions)}/{self.max_pool_size}",
            "transactions": self.pending_transactions
        }

def create_coinbase_transaction(miner_address: str, reward: float, 
                              block_height: int) -> Dict:
    """Create coinbase transaction for mining reward"""
    return {
        "transaction_id": f"coinbase_{block_height}_{int(time.time())}",
        "sender": "system",
        "recipient": miner_address,
        "amount": reward,
        "timestamp": time.time(),
        "signature": f"coinbase_reward_block_{block_height}",
        "sender_public_key": "system_key"
    }

def calculate_transaction_fee(transaction: Dict, fee_rate: float = 0.001) -> float:
    """Calculate transaction fee based on transaction size"""
    # Simple fee calculation - in real implementation, this would be more complex
    tx_size = len(json.dumps(transaction))
    return max(fee_rate, tx_size * 0.00001)  # Minimum fee or size-based fee

if __name__ == "__main__":
    # Test transaction system
    from blockchain import Blockchain
    from wallet import WalletManager, create_signed_transaction
    
    print("Testing Transaction System...")
    
    # Create blockchain and wallets
    blockchain = Blockchain(difficulty=2)
    wallet_manager = WalletManager()
    
    # Create test wallets
    alice_wallet = wallet_manager.create_wallet("alice")
    bob_wallet = wallet_manager.create_wallet("bob")
    
    print(f"Alice address: {alice_wallet.address}")
    print(f"Bob address: {bob_wallet.address}")
    
    # Give Alice some initial coins by mining
    print("\nMining initial block for Alice...")
    blockchain.mine_pending_transactions(alice_wallet.address)
    print(f"Alice balance: {blockchain.get_balance(alice_wallet.address)}")
    
    # Create transaction pool
    tx_pool = TransactionPool(blockchain)
    
    # Create a transaction from Alice to Bob
    transaction = create_signed_transaction(alice_wallet, bob_wallet.address, 5.0)
    
    # Add transaction to pool
    success, message = tx_pool.add_transaction(transaction)
    print(f"\nTransaction added: {success}, {message}")
    
    # Get pool stats
    stats = tx_pool.get_pool_stats()
    print(f"Pool stats: {stats['pool_usage']} transactions")
    
    # Mine the transaction
    print("\nMining transaction...")
    blockchain.mempool = tx_pool.pending_transactions.copy()
    block = blockchain.mine_pending_transactions(alice_wallet.address)
    
    # Remove mined transactions from pool
    mined_tx_ids = [tx.get("transaction_id") for tx in block.transactions]
    tx_pool.remove_transactions(mined_tx_ids)
    
    print(f"Alice balance after mining: {blockchain.get_balance(alice_wallet.address)}")
    print(f"Bob balance: {blockchain.get_balance(bob_wallet.address)}")
    print(f"Remaining transactions in pool: {len(tx_pool.pending_transactions)}")