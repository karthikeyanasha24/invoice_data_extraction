'use client';

import { useState, useEffect, useRef } from 'react';
import { ProcessingStepResult } from '@/types';
import { CheckCircle, XCircle, Clock, AlertTriangle, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { fileApi } from '@/lib/api';

interface ProcessingStatusTrackerProps {
  trackingId: string;
  onComplete?: (finalStatus: ProcessingStepResult[]) => void;
  onError?: (error: string) => void;
  pollInterval?: number; // milliseconds
  autoStopPolling?: boolean; // Whether to stop polling when complete
}

export default function ProcessingStatusTracker({
  trackingId,
  onComplete,
  onError,
  pollInterval = 500, // Poll every 500ms for faster updates
  autoStopPolling = true // Stop polling when complete by default
}: ProcessingStatusTrackerProps) {
  const [steps, setSteps] = useState<ProcessingStepResult[]>([]);
  const [isCompleted, setIsCompleted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const completedRef = useRef(false);

  const fetchStatus = async () => {
    try {
      const status = await fileApi.getProcessingStatus(trackingId);
      
      if (status) {
        // Update steps - create new array to ensure React detects change
        if (status.processing_steps && status.processing_steps.length > 0) {
          const newSteps = [...status.processing_steps];
          setSteps(newSteps);
          
          // Check if processing is complete (has step 6 or 7 - Database Save)
          const hasFinalStep = status.processing_steps.some(step => 
            step.step_number === 6 || step.step_number === 7
          );
          
          if (hasFinalStep && !completedRef.current) {
            completedRef.current = true;
            setIsCompleted(true);
            if (onComplete) {
              onComplete(status.processing_steps);
            }
            // Stop polling only if autoStopPolling is enabled
            if (autoStopPolling && pollingRef.current) {
              clearInterval(pollingRef.current);
              pollingRef.current = null;
            }
          }
        } else {
          // Status initialized but no steps yet - processing just started
          setSteps([]);
          setError(null); // Clear any previous errors
        }
      }
    } catch (err: any) {
      console.error('Failed to fetch processing status:', err);
      if (err.message?.includes('404') || err.message?.includes('not found')) {
        // Status not found - might be still initializing or invalid tracking ID
        if (!error) {
          setError('Processing status not available yet. Please wait...');
        }
      } else {
        setError(err.message || 'Failed to fetch processing status');
        if (onError) {
          onError(err.message || 'Failed to fetch processing status');
        }
        // Stop polling on error
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      }
    }
  };

  useEffect(() => {
    if (!trackingId) return;

    // Initial fetch
    fetchStatus();

    // Start polling
    pollingRef.current = setInterval(() => {
      if (!completedRef.current) {
        fetchStatus();
      }
    }, pollInterval);

    // Cleanup on unmount
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, [trackingId, pollInterval]);

  const getStepIcon = (step: ProcessingStepResult) => {
    if (step.success === undefined) {
      return <Loader2 className="h-5 w-5 text-gray-400 animate-spin" />;
    }
    if (step.success) {
      return <CheckCircle className="h-5 w-5 text-green-500" />;
    }
    return <XCircle className="h-5 w-5 text-red-500" />;
  };

  const getStepStatusColor = (step: ProcessingStepResult) => {
    if (step.success === undefined) {
      return 'bg-gray-100 text-gray-600 border-gray-300';
    }
    if (step.success) {
      return 'bg-green-50 text-green-800 border-green-200';
    }
    return 'bg-red-50 text-red-800 border-red-200';
  };

  // Expected steps in order (matching backend step numbers)
  const expectedSteps = [
    { number: 1, name: 'File Upload' },
    { number: 2, name: 'XML Validation' },
    { number: 3, name: 'EDI Conversion' },
    { number: 4, name: 'EDI Format Validation' },
    { number: 5, name: 'Third-party Endpoint' },
    { number: 6, name: 'Database Save' }
  ];

  // Find the current step being processed
  // The current step is the next one that hasn't been completed yet
  const currentStepNumber = (() => {
    if (steps.length === 0) return 1;
    // Find the highest step number that's been completed
    const completedSteps = steps.filter(s => s.success === true);
    if (completedSteps.length === 0) {
      // No completed steps yet, first step is current
      return 1;
    }
    // Find if there's a failed step - if so, that's the current (failed) step
    const failedStep = steps.find(s => s.success === false);
    if (failedStep) {
      // If there's a failed step, that's where we are (processing stopped)
      return failedStep.step_number;
    }
    // All existing steps are complete, next step is the one after the last step
    const maxStepNumber = Math.max(...steps.map(s => s.step_number));
    return Math.min(maxStepNumber + 1, 7); // Cap at step 7 (Database Save)
  })();

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">Processing Status</h3>
        {!isCompleted && (
          <div className="flex items-center space-x-2 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Processing...</span>
          </div>
        )}
        {isCompleted && (
          <div className="flex items-center space-x-2 text-sm text-green-600">
            <CheckCircle className="h-4 w-4" />
            <span>Completed</span>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
          <div className="flex items-center space-x-2">
            <AlertTriangle className="h-4 w-4 text-yellow-600" />
            <p className="text-sm text-yellow-800">{error}</p>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {expectedSteps.map((expectedStep) => {
          const step = steps.find(s => s.step_number === expectedStep.number);
          // Step is current if it matches the current step number being processed
          const isCurrentStep = expectedStep.number === currentStepNumber;
          const isCompleted = step?.success === true;
          const isFailed = step?.success === false;
          const isPending = !step && expectedStep.number > currentStepNumber;

          return (
            <div
              key={expectedStep.number}
              className={cn(
                "border rounded-lg p-4 transition-all duration-300",
                isCurrentStep
                  ? "border-blue-400 bg-blue-50 shadow-md ring-2 ring-blue-200"
                  : isCompleted
                    ? "border-green-200 bg-green-50"
                    : isFailed
                      ? "border-red-200 bg-red-50"
                      : isPending
                        ? "border-gray-200 bg-gray-50 opacity-60"
                        : "border-gray-200 bg-gray-50"
              )}
            >
              <div className="flex items-start space-x-3">
                <div className="flex-shrink-0 mt-0.5">
                  {isCurrentStep && !step ? (
                    <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
                  ) : step ? (
                    getStepIcon(step)
                  ) : (
                    <div className="w-5 h-5 rounded-full border-2 border-gray-300" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-gray-900">
                      {expectedStep.number}. {step?.step_name || expectedStep.name}
                    </h4>
                    <span className={cn(
                      "px-2 py-1 rounded-full text-xs font-medium",
                      isCurrentStep
                        ? "bg-blue-100 text-blue-800 animate-pulse"
                        : isCompleted
                          ? "bg-green-100 text-green-800"
                          : isFailed
                            ? "bg-red-100 text-red-800"
                            : isPending
                              ? "bg-gray-100 text-gray-500"
                              : "bg-gray-100 text-gray-600"
                    )}>
                      {isCurrentStep
                        ? 'Processing...'
                        : isCompleted
                          ? 'Success'
                          : isFailed
                            ? 'Failed'
                            : isPending
                              ? 'Pending'
                              : 'Waiting'
                      }
                    </span>
                  </div>
                  
                  {step && (
                    <>
                      {step.message && (
                        <div className="mt-2">
                          <p className="text-sm text-gray-700 font-medium">{step.message}</p>
                          {/* Show additional details for specific steps */}
                          {step.step_name === "XML Validation" && step.message.includes("AI correction") && (
                            <p className="text-xs text-blue-600 mt-1 italic">✓ AI correction applied</p>
                          )}
                          {step.step_name === "EDI Conversion" && (
                            <div className="mt-1 text-xs text-gray-600">
                              {step.message.includes("Customer ID") || step.message.includes("Customer:") ? (
                                <div className="flex flex-wrap gap-2 mt-1">
                                  {step.message.match(/Customer ID: ([^,]+)/) && (
                                    <span className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded">ID: {step.message.match(/Customer ID: ([^,]+)/)?.[1]}</span>
                                  )}
                                  {step.message.match(/Customer: ([^,]+)/) && (
                                    <span className="px-2 py-0.5 bg-purple-50 text-purple-700 rounded">{step.message.match(/Customer: ([^,]+)/)?.[1]}</span>
                                  )}
                                  {step.message.match(/Format: ([^,]+)/) && (
                                    <span className="px-2 py-0.5 bg-green-50 text-green-700 rounded">Format: {step.message.match(/Format: ([^,]+)/)?.[1]}</span>
                                  )}
                                </div>
                              ) : null}
                            </div>
                          )}
                        </div>
                      )}
                      {step.duration_seconds !== undefined && step.duration_seconds > 0 && (
                        <div className="flex items-center space-x-1 text-xs text-gray-500 mt-1">
                          <Clock className="h-3 w-3" />
                          <span>{step.duration_seconds.toFixed(2)}s</span>
                        </div>
                      )}
                      {isFailed && step.error_details && step.error_details.length > 0 && (
                        <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded">
                          <p className="text-xs font-medium text-red-800 mb-1">Validation Errors:</p>
                          <ul className="text-xs text-red-700 space-y-1">
                            {step.error_details.slice(0, 3).map((error, idx) => (
                              <li key={idx} className="flex items-start">
                                <span className="mr-1">•</span>
                                <span>{error.user_message || error.error_message}</span>
                              </li>
                            ))}
                            {step.error_details.length > 3 && (
                              <li className="text-red-600 italic">
                                +{step.error_details.length - 3} more errors
                              </li>
                            )}
                          </ul>
                        </div>
                      )}
                      {isCompleted && step.step_name === "XML Validation" && step.message && step.message.includes("Warnings") && (
                        <div className="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded">
                          <p className="text-xs font-medium text-yellow-800">Note: Validation passed with warnings</p>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {steps.length === 0 && !error && (
        <div className="text-center py-8">
          <Loader2 className="h-8 w-8 text-gray-400 animate-spin mx-auto mb-2" />
          <p className="text-sm text-gray-500">Initializing processing...</p>
          <p className="text-xs text-gray-400 mt-2">Tracking ID: {trackingId}</p>
        </div>
      )}
    </div>
  );
}

