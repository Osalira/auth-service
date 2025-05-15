import pika
import json
import logging
import os
from datetime import datetime
import threading
import time
import queue
from pika.exceptions import AMQPConnectionError, ConnectionClosedByBroker

logger = logging.getLogger(__name__)

# Create a connection pool for RabbitMQ
class RabbitMQConnectionPool:
    """Thread-safe connection pool for RabbitMQ"""
    
    def __init__(self, max_connections=10):
        self.max_connections = max_connections
        self.connections = queue.Queue(max_connections)
        self.connection_count = 0
        self.lock = threading.RLock()
        
        # Connection parameters
        self.host = os.getenv('RABBITMQ_HOST', 'rabbitmq')
        self.port = int(os.getenv('RABBITMQ_PORT', 5672))
        self.username = os.getenv('RABBITMQ_USER', 'user')
        self.password = os.getenv('RABBITMQ_PASSWORD', 'password')
        
        # Initialize exchanges
        self.exchanges = {
            'user_events': 'topic',
            'order_events': 'topic',
            'system_events': 'topic'
        }
    
    def get_connection(self):
        """Get a connection from the pool or create a new one if needed"""
        try:
            # Try to get a connection from the pool
            return self.connections.get(block=False)
        except queue.Empty:
            # If pool is empty, create a new connection if we haven't reached max
            with self.lock:
                if self.connection_count < self.max_connections:
                    connection = self._create_connection()
                    if connection:
                        self.connection_count += 1
                        return connection
            
            # If we've reached max connections, wait for one to become available
            try:
                return self.connections.get(block=True, timeout=5)
            except queue.Empty:
                logger.error("Timed out waiting for available RabbitMQ connection")
                return None
    
    def release_connection(self, connection):
        """Return a connection to the pool"""
        if connection and connection.is_open:
            try:
                self.connections.put(connection, block=False)
            except queue.Full:
                # If the pool is full, close the excess connection
                connection.close()
                with self.lock:
                    self.connection_count -= 1
        elif connection:
            # Connection is closed, decrement count
            with self.lock:
                self.connection_count -= 1
    
    def _create_connection(self):
        """Create a new RabbitMQ connection"""
        credentials = pika.PlainCredentials(self.username, self.password)
        parameters = pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            virtual_host='/',
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300
        )
        
        # Try to connect with retry logic
        max_retries = 3
        retry_interval = 2
        for attempt in range(max_retries):
            try:
                connection = pika.BlockingConnection(parameters)
                channel = connection.channel()
                
                # Declare exchanges
                for exchange, exchange_type in self.exchanges.items():
                    channel.exchange_declare(
                        exchange=exchange,
                        exchange_type=exchange_type,
                        durable=True
                    )
                
                logger.info("Created new RabbitMQ connection")
                return connection
            except Exception as e:
                logger.warning(f"Failed to create RabbitMQ connection (attempt {attempt+1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)
        
        logger.error("Failed to create RabbitMQ connection after multiple attempts")
        return None
    
    def close_all(self):
        """Close all connections in the pool"""
        with self.lock:
            while not self.connections.empty():
                try:
                    conn = self.connections.get(block=False)
                    if conn and conn.is_open:
                        conn.close()
                except Exception as e:
                    logger.error(f"Error closing connection: {str(e)}")
            self.connection_count = 0

# Global connection pool
connection_pool = RabbitMQConnectionPool(max_connections=50)

class RabbitMQClient:
    """RabbitMQ client for publishing and consuming events"""
    
    def __init__(self):
        """Initialize RabbitMQ client"""
        self.host = os.getenv('RABBITMQ_HOST', 'rabbitmq')
        self.port = int(os.getenv('RABBITMQ_PORT', 5672))
        self.username = os.getenv('RABBITMQ_USER', 'user')
        self.password = os.getenv('RABBITMQ_PASSWORD', 'password')
        self.consumer_threads = []
        
        # Define exchanges
        self.exchanges = {
            'user_events': 'topic',
            'order_events': 'topic',
            'system_events': 'topic'
        }
        
        # Message queue for batch publishing
        self.message_queue = queue.Queue()
        self.is_publisher_running = False
        self.publisher_lock = threading.Lock()

    def start_publisher_thread(self):
        """Start the background publisher thread if not already running"""
        with self.publisher_lock:
            if not self.is_publisher_running:
                thread = threading.Thread(target=self._publisher_worker)
                thread.daemon = True
                thread.start()
                self.is_publisher_running = True
                logger.info("Started RabbitMQ publisher thread")

    def _publisher_worker(self):
        """Background worker that publishes messages from the queue"""
        batch_size = 50  # Process messages in batches (increased from 10)
        wait_time = 0.1  # Wait time between batches when queue is empty
        
        while True:
            messages = []
            try:
                # Collect up to batch_size messages from the queue
                for _ in range(batch_size):
                    try:
                        messages.append(self.message_queue.get(block=False))
                    except queue.Empty:
                        break
                
                if not messages:
                    # If no messages, sleep briefly and continue
                    time.sleep(wait_time)
                    continue
                
                # Process the batch of messages
                connection = connection_pool.get_connection()
                if not connection:
                    # If couldn't get connection, put messages back in queue
                    for msg in messages:
                        self.message_queue.put(msg)
                    time.sleep(1)  # Wait before retrying
                    continue
                
                try:
                    channel = connection.channel()
                    
                    # Publish all messages in batch
                    for exchange, routing_key, message in messages:
                        try:
                            channel.basic_publish(
                                exchange=exchange,
                                routing_key=routing_key,
                                body=json.dumps(message),
                                properties=pika.BasicProperties(
                                    delivery_mode=2,  # Make message persistent
                                    content_type='application/json'
                                ),
                                mandatory=False  # Don't wait for confirmation
                            )
                            logger.debug(f"Published event to {exchange} with routing key {routing_key}")
                        except Exception as e:
                            logger.error(f"Error publishing message: {str(e)}")
                            # Could re-queue message here if needed
                    
                    # Mark all messages as done
                    for _ in messages:
                        self.message_queue.task_done()
                        
                except Exception as e:
                    logger.error(f"Error in publisher batch processing: {str(e)}")
                    # Re-queue messages on error
                    for msg in messages:
                        self.message_queue.put(msg)
                finally:
                    connection_pool.release_connection(connection)
                    
            except Exception as e:
                logger.error(f"Unexpected error in publisher thread: {str(e)}")
                time.sleep(1)  # Wait before continuing

    def publish_event(self, exchange, routing_key, message, retry=True):
        """Queue an event for publishing to RabbitMQ"""
        # Add timestamp if not present
        if 'timestamp' not in message:
            message['timestamp'] = datetime.now().isoformat()
            
        # Add trace_id if not present
        if 'trace_id' not in message:
            import uuid
            message['trace_id'] = uuid.uuid4().hex[:8]
        
        # Start publisher thread if not already running
        if not self.is_publisher_running:
            self.start_publisher_thread()
        
        # Add message to the queue
        self.message_queue.put((exchange, routing_key, message))
        return True

    def start_consumer(self, queue_name, routing_keys, exchange, callback):
        """Start a consumer for the given queue and routing keys"""
        def consumer_thread():
            while True:
                connection = None
                try:
                    # Get connection from pool
                    connection = connection_pool.get_connection()
                    if not connection:
                        logger.error("Cannot start consumer because RabbitMQ connection failed")
                        time.sleep(5)
                        continue
                    
                    channel = connection.channel()
                    
                    # Declare queue
                    result = channel.queue_declare(
                        queue=queue_name, 
                        durable=True
                    )
                    
                    # Bind queue to exchange with routing keys
                    for key in routing_keys:
                        channel.queue_bind(
                            exchange=exchange,
                            queue=queue_name,
                            routing_key=key
                        )
                    
                    # Define callback wrapper to handle acknowledgments
                    def callback_wrapper(ch, method, properties, body):
                        try:
                            callback(json.loads(body))
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                        except Exception as e:
                            logger.error(f"Error processing message: {str(e)}")
                            # Negative acknowledgment with requeue
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    
                    # Set up consumer
                    channel.basic_qos(prefetch_count=1)
                    channel.basic_consume(
                        queue=queue_name,
                        on_message_callback=callback_wrapper
                    )
                    
                    logger.info(f"Started consuming from {queue_name} bound to {exchange}")
                    channel.start_consuming()
                    
                except (ConnectionClosedByBroker, AMQPConnectionError) as e:
                    logger.warning(f"RabbitMQ connection error: {str(e)}")
                    time.sleep(5)
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error in consumer: {str(e)}")
                    time.sleep(5)
                    continue
                finally:
                    if connection:
                        connection_pool.release_connection(connection)
        
        # Start consumer in a separate thread
        consumer = threading.Thread(target=consumer_thread)
        consumer.daemon = True
        consumer.start()
        self.consumer_threads.append(consumer)
        
        return consumer

    def close(self):
        """Close the RabbitMQ connections"""
        logger.info("Closing RabbitMQ connections")

# Create a global RabbitMQ client instance
rabbitmq_client = RabbitMQClient()

# Helper function to publish an event
def publish_event(exchange, routing_key, message=None):
    """Publish an event to RabbitMQ"""
    # Backward compatibility - if only two arguments are provided,
    # assume the second argument is the message and use event_type as routing_key
    if message is None:
        message = routing_key
        # Extract routing key from the message's event_type field
        routing_key = message.get('event_type', 'default.event')
    
    return rabbitmq_client.publish_event(exchange, routing_key, message)

# Helper function to start a consumer
def start_consumer(queue_name, routing_keys, exchange, callback):
    """Start a consumer for the given queue and routing keys"""
    return rabbitmq_client.start_consumer(queue_name, routing_keys, exchange, callback) 