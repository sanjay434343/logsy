import hashlib
import json
import os
from typing import Tuple, Dict, Optional
from ecdsa import SigningKey, VerifyingKey, SECP256k1
from ecdsa.util import sigencode_string, sigdecode_string
import base64
import time

class Wallet:
    def __init__(self, private_key: Optional[str] = None):
        """Initialize wallet with existing private key or generate new one"""
        if private_key:
            self.private_key = SigningKey.from_string(
                bytes.fromhex(private_key), 
                curve=SECP256k1
            )
        else:
            self.private_key = SigningKey.generate(curve=SECP256k1)
        
        self.public_key = self.private_key.get_verifying_key()
        self.address = self.generate_address()
    
    def generate_address(self) -> str:
        """Generate address from public key using SHA-256"""
        public_key_bytes = self.public_key.to_string()
        address_hash = hashlib.sha256(public_key_bytes).hexdigest()
        return address_hash[:40]  # Use first 40 characters as address
    
    def get_private_key_hex(self) -> str:
        """Get private key as hex string"""
        return self.private_key.to_string().hex()
    
    def get_public_key_hex(self) -> str:
        """Get public key as hex string"""
        return self.public_key.to_string().hex()
    
    def sign_transaction(self, transaction_data: Dict) -> str:
        """Sign transaction data with private key"""
        # Create deterministic transaction string for signing
        tx_string = json.dumps({
            "sender": transaction_data["sender"],
            "recipient": transaction_data["recipient"],
            "amount": transaction_data["amount"],
            "timestamp": transaction_data["timestamp"]
        }, sort_keys=True)
        
        # Sign the transaction hash
        tx_hash = hashlib.sha256(tx_string.encode()).digest()
        signature = self.private_key.sign(tx_hash, sigencode=sigencode_string)
        
        return base64.b64encode(signature).decode()
    
    def to_dict(self) -> Dict:
        """Convert wallet to dictionary for JSON serialization"""
        return {
            "private_key": self.get_private_key_hex(),
            "public_key": self.get_public_key_hex(),
            "address": self.address
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Wallet':
        """Create wallet from dictionary"""
        return cls(private_key=data["private_key"])

class WalletManager:
    def __init__(self, wallet_dir: str = "data/wallets"):
        self.wallet_dir = wallet_dir
        os.makedirs(wallet_dir, exist_ok=True)
    
    def create_wallet(self, wallet_name: str = None) -> Wallet:
        """Create a new wallet and save it"""
        wallet = Wallet()
        
        if not wallet_name:
            wallet_name = f"wallet_{int(time.time())}"
        
        self.save_wallet(wallet, wallet_name)
        return wallet
    
    def save_wallet(self, wallet: Wallet, wallet_name: str) -> None:
        """Save wallet to file"""
        wallet_file = os.path.join(self.wallet_dir, f"{wallet_name}.json")
        
        with open(wallet_file, 'w') as f:
            json.dump(wallet.to_dict(), f, indent=2)
        
        print(f"Wallet saved: {wallet_file}")
    
    def load_wallet(self, wallet_name: str) -> Optional[Wallet]:
        """Load wallet from file"""
        wallet_file = os.path.join(self.wallet_dir, f"{wallet_name}.json")
        
        if not os.path.exists(wallet_file):
            return None
        
        try:
            with open(wallet_file, 'r') as f:
                wallet_data = json.load(f)
            
            return Wallet.from_dict(wallet_data)
        
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error loading wallet: {e}")
            return None
    
    def list_wallets(self) -> list:
        """List all available wallets"""
        wallets = []
        for filename in os.listdir(self.wallet_dir):
            if filename.endswith('.json'):
                wallet_name = filename[:-5]  # Remove .json extension
                wallets.append(wallet_name)
        return wallets
    
    def delete_wallet(self, wallet_name: str) -> bool:
        """Delete a wallet file"""
        wallet_file = os.path.join(self.wallet_dir, f"{wallet_name}.json")
        
        if os.path.exists(wallet_file):
            os.remove(wallet_file)
            return True
        return False

def verify_transaction_signature(transaction: Dict, public_key_hex: str) -> bool:
    """Verify transaction signature using public key"""
    try:
        # Recreate the transaction string that was signed
        tx_string = json.dumps({
            "sender": transaction["sender"],
            "recipient": transaction["recipient"],
            "amount": transaction["amount"],
            "timestamp": transaction["timestamp"]
        }, sort_keys=True)
        
        # Hash the transaction string
        tx_hash = hashlib.sha256(tx_string.encode()).digest()
        
        # Decode the signature
        signature = base64.b64decode(transaction["signature"])
        
        # Recreate public key from hex
        public_key = VerifyingKey.from_string(
            bytes.fromhex(public_key_hex), 
            curve=SECP256k1
        )
        
        # Verify signature
        return public_key.verify(signature, tx_hash, sigdecode=sigdecode_string)
    
    except Exception as e:
        print(f"Signature verification failed: {e}")
        return False

def create_signed_transaction(sender_wallet: Wallet, recipient_address: str, 
                            amount: float) -> Dict:
    """Create a signed transaction"""
    transaction = {
        "sender": sender_wallet.address,
        "recipient": recipient_address,
        "amount": amount,
        "timestamp": time.time(),
        "sender_public_key": sender_wallet.get_public_key_hex()
    }
    
    # Sign the transaction
    transaction["signature"] = sender_wallet.sign_transaction(transaction)
    
    return transaction

if __name__ == "__main__":
    # Test wallet functionality
    print("Testing Wallet System...")
    
    # Create wallet manager
    wallet_manager = WalletManager()
    
    # Create two test wallets
    wallet1 = wallet_manager.create_wallet("alice")
    wallet2 = wallet_manager.create_wallet("bob")
    
    print(f"Alice's address: {wallet1.address}")
    print(f"Bob's address: {wallet2.address}")
    
    # Create a transaction from Alice to Bob
    transaction = create_signed_transaction(wallet1, wallet2.address, 5.0)
    
    print(f"Transaction created: {transaction}")
    
    # Verify the transaction signature
    is_valid = verify_transaction_signature(transaction, wallet1.get_public_key_hex())
    print(f"Transaction signature valid: {is_valid}")
    
    # Test wallet loading
    loaded_wallet = wallet_manager.load_wallet("alice")
    print(f"Loaded wallet address: {loaded_wallet.address}")
    print(f"Addresses match: {wallet1.address == loaded_wallet.address}")
    
    # List all wallets
    print(f"Available wallets: {wallet_manager.list_wallets()}")

# No changes needed for real usage.