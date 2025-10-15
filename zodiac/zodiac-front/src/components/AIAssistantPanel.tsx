'use client';

import { useState, useRef, useEffect } from 'react';
import { X, Send, Bot, User, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { LLMMessage, FailedInvoiceDetails } from '@/types';

interface AIAssistantPanelProps {
  invoiceDetails: FailedInvoiceDetails | null;
  isOpen: boolean;
  onClose: () => void;
}

export default function AIAssistantPanel({ 
  invoiceDetails, 
  isOpen, 
  onClose 
}: AIAssistantPanelProps) {
  const [messages, setMessages] = useState<LLMMessage[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (isOpen && messages.length === 0 && invoiceDetails) {
      // Initialize with system message about the invoice
      const systemMessage: LLMMessage = {
        id: '1',
        role: 'assistant',
        content: `I can see that your invoice processing failed. Here are the details:

**XML Validation**: ${invoiceDetails.xml_validation_pass ? '✅ Passed' : '❌ Failed'}
${invoiceDetails.xml_convert_message ? `- ${invoiceDetails.xml_convert_message}` : ''}

**EDI Conversion**: ${invoiceDetails.edi_convert_pass ? '✅ Passed' : '❌ Failed'}
${invoiceDetails.edi_convert_message ? `- ${invoiceDetails.edi_convert_message}` : ''}

I'm here to help you understand what went wrong and guide you through fixing the issues. What would you like to know about your invoice processing?`,
        timestamp: new Date()
      };
      setMessages([systemMessage]);
    }
  }, [isOpen, messages.length, invoiceDetails]);

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || isLoading) return;

    const userMessage: LLMMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: inputMessage.trim(),
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setInputMessage('');
    setIsLoading(true);

    try {
      // Simulate AI response - in real implementation, this would call your LLM API
      await new Promise(resolve => setTimeout(resolve, 1000)); // Simulate API call
      
      const aiResponse: LLMMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `I understand your question about "${inputMessage}". Let me help you with that. Based on the error details, I can suggest some solutions:

1. **Check XML Structure**: Make sure your XML file has proper opening and closing tags
2. **Validate Required Fields**: Ensure all required invoice fields are present
3. **Format Compliance**: Verify the XML follows the expected invoice schema

Would you like me to provide more specific guidance on any of these areas?`,
        timestamp: new Date()
      };

      setMessages(prev => [...prev, aiResponse]);
    } catch (error) {
      console.error('Error sending message:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className={cn(
      "bg-white shadow-lg border border-gray-200 transition-all duration-300 transform flex flex-col",
      "animate-slide-in-right",
      // Use max-height instead of h-full to prevent stretching
      "max-h-[calc(100vh-200px)] min-h-[400px]"
    )}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 bg-purple-50 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Bot className="h-5 w-5 text-purple-600" />
            <span className="font-medium text-gray-900">AI Assistant</span>
            {invoiceDetails && (
              <span className="text-xs text-gray-500">
                ({invoiceDetails.tracking_id.slice(0, 8)}...)
              </span>
            )}
          </div>
          <div className="flex items-center space-x-1">
            <button
              onClick={() => setIsMinimized(!isMinimized)}
              className="p-1 text-gray-400 hover:text-gray-600"
              title={isMinimized ? "Expand" : "Minimize"}
            >
              {isMinimized ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            <button
              onClick={onClose}
              className="p-1 text-gray-400 hover:text-gray-600"
              title="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {!isMinimized && (
        <>
          {/* Messages Container - Fixed height with scroll */}
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4" style={{ maxHeight: '300px', minHeight: '200px' }}>
            {messages.map((message) => (
              <div
                key={message.id}
                className={cn(
                  "flex space-x-2",
                  message.role === 'user' ? "justify-end" : "justify-start"
                )}
              >
                {message.role === 'assistant' && (
                  <div className="flex-shrink-0">
                    <div className="h-6 w-6 bg-purple-100 rounded-full flex items-center justify-center">
                      <Bot className="h-3 w-3 text-purple-600" />
                    </div>
                  </div>
                )}
                
                <div
                  className={cn(
                    "max-w-xs px-3 py-2 rounded-lg text-sm",
                    message.role === 'user'
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 text-gray-900"
                  )}
                >
                  <p className="whitespace-pre-wrap">{message.content}</p>
                  <p className="text-xs opacity-70 mt-1">
                    {message.timestamp.toLocaleTimeString()}
                  </p>
                </div>

                {message.role === 'user' && (
                  <div className="flex-shrink-0">
                    <div className="h-6 w-6 bg-blue-100 rounded-full flex items-center justify-center">
                      <User className="h-3 w-3 text-blue-600" />
                    </div>
                  </div>
                )}
              </div>
            ))}
            
            {isLoading && (
              <div className="flex space-x-2 justify-start">
                <div className="flex-shrink-0">
                  <div className="h-6 w-6 bg-purple-100 rounded-full flex items-center justify-center">
                    <Bot className="h-3 w-3 text-purple-600" />
                  </div>
                </div>
                <div className="bg-gray-100 text-gray-900 px-3 py-2 rounded-lg">
                  <div className="flex space-x-1">
                    <div className="w-1 h-1 bg-gray-400 rounded-full animate-bounce"></div>
                    <div className="w-1 h-1 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                    <div className="w-1 h-1 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                  </div>
                </div>
              </div>
            )}
            
            <div ref={messagesEndRef} />
          </div>

          {/* Input - Always positioned at bottom of panel */}
          <div className="px-4 py-3 border-t border-gray-200 flex-shrink-0 bg-white">
            <div className="flex space-x-2">
              <input
                type="text"
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Ask me anything about your invoice..."
                className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                disabled={isLoading}
              />
              <button
                onClick={handleSendMessage}
                disabled={!inputMessage.trim() || isLoading}
                className={cn(
                  "px-3 py-2 rounded-md text-sm font-medium flex items-center",
                  inputMessage.trim() && !isLoading
                    ? "bg-purple-600 text-white hover:bg-purple-700"
                    : "bg-gray-300 text-gray-500 cursor-not-allowed"
                )}
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </>
      )}

      {/* Minimized State */}
      {isMinimized && (
        <div className="px-4 py-3 flex-shrink-0">
          <div className="text-sm text-gray-600">
            <div className="flex items-center space-x-2">
              <Bot className="h-4 w-4 text-purple-600" />
              <span>AI Assistant is ready to help</span>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Click the expand button to continue the conversation
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
