'use client';

import { useState } from 'react';
import { Sparkles, Clock, CheckCircle, XCircle, ChevronDown, ChevronUp } from 'lucide-react';
import ReactMarkdown from 'react-markdown';

type ModelResponse = {
  name: string;
  content: string;
  response_time_ms: number;
  success: boolean;
  error?: string;
  token_usage?: {
    prompt_tokens: number;
    completion_tokens: number;
  };
};

type MultiModelResult = {
  synthesized_answer: string;
  best_model: string;
  total_time_ms: number;
  models: ModelResponse[];
};

interface MultiModelComparisonProps {
  result: MultiModelResult;
}

const getModelColor = (modelName: string): string => {
  if (modelName.includes('OpenAI') || modelName.includes('GPT')) {
    return 'blue';
  } else if (modelName.includes('Gemini') || modelName.includes('Google')) {
    return 'green';
  } else if (modelName.includes('Claude') || modelName.includes('Anthropic')) {
    return 'purple';
  }
  return 'gray';
};

const getColorClasses = (color: string) => {
  const colors = {
    blue: {
      border: 'border-blue-200',
      bg: 'bg-blue-50',
      text: 'text-blue-700',
      badge: 'bg-blue-100 text-blue-700',
      icon: 'text-blue-500',
    },
    green: {
      border: 'border-green-200',
      bg: 'bg-green-50',
      text: 'text-green-700',
      badge: 'bg-green-100 text-green-700',
      icon: 'text-green-500',
    },
    purple: {
      border: 'border-purple-200',
      bg: 'bg-purple-50',
      text: 'text-purple-700',
      badge: 'bg-purple-100 text-purple-700',
      icon: 'text-purple-500',
    },
    gray: {
      border: 'border-gray-200',
      bg: 'bg-gray-50',
      text: 'text-gray-700',
      badge: 'bg-gray-100 text-gray-700',
      icon: 'text-gray-500',
    },
  };
  return colors[color as keyof typeof colors] || colors.gray;
};

export default function MultiModelComparison({ result }: MultiModelComparisonProps) {
  const [expandedModel, setExpandedModel] = useState<string | null>(null);
  const [showSynthesis, setShowSynthesis] = useState(true);

  return (
    <div className="space-y-3 sm:space-y-4 mt-4">
      {/* Synthesized Answer - Prominent Display */}
      <div className="rounded-lg sm:rounded-xl border-2 border-indigo-200 bg-white shadow-md overflow-hidden">
        <div className="px-3 sm:px-4 py-2.5 sm:py-3 border-b border-indigo-100 bg-indigo-50">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 sm:h-5 sm:w-5 text-indigo-600 flex-shrink-0" />
              <h4 className="text-xs sm:text-sm font-semibold text-indigo-900">Best Answer (Synthesized)</h4>
            </div>
            <button
              onClick={() => setShowSynthesis(!showSynthesis)}
              className="sm:hidden p-1 hover:bg-indigo-100 rounded"
              aria-label={showSynthesis ? 'Collapse' : 'Expand'}
            >
              {showSynthesis ? (
                <ChevronUp className="h-4 w-4 text-indigo-600" />
              ) : (
                <ChevronDown className="h-4 w-4 text-indigo-600" />
              )}
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3 mt-2 text-[10px] sm:text-xs text-indigo-600">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3 sm:h-3.5 sm:w-3.5" />
              {(result.total_time_ms / 1000).toFixed(1)}s
            </span>
            <span className="px-2 py-0.5 rounded-full bg-indigo-100 font-medium truncate max-w-[200px]">
              Best: {result.best_model.split(' ')[0]}
            </span>
          </div>
        </div>
        {showSynthesis && (
          <div className="p-3 sm:p-4">
            <div className="prose prose-sm sm:prose max-w-none text-gray-800">
              <ReactMarkdown
                components={{
                  p: ({ children }) => <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>,
                  strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
                  ul: ({ children }) => <ul className="space-y-1.5 ml-4 my-2">{children}</ul>,
                  ol: ({ children }) => <ol className="space-y-1.5 ml-4 my-2">{children}</ol>,
                  li: ({ children }) => <li className="text-gray-700">{children}</li>,
                  h3: ({ children }) => <h3 className="font-semibold text-gray-900 mt-3 mb-2 text-sm">{children}</h3>,
                }}
              >
                {result.synthesized_answer}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </div>

      {/* Individual Model Responses - Responsive Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-4">
        {result.models.map((model, index) => {
          const color = getModelColor(model.name);
          const classes = getColorClasses(color);
          const isExpanded = expandedModel === model.name;
          const isBest = model.name === result.best_model;

          return (
            <div
              key={index}
              className={`rounded-lg sm:rounded-xl border ${classes.border} bg-white shadow-sm overflow-hidden transition-all ${
                isBest ? 'ring-2 ring-offset-1 sm:ring-offset-2 ring-indigo-400' : ''
              }`}
            >
              <div className={`px-3 py-2 sm:py-2.5 border-b ${classes.border} ${classes.bg}`}>
                <div className="flex items-center justify-between mb-1 sm:mb-1.5">
                  <h5 className={`text-[11px] sm:text-xs font-semibold ${classes.text} flex items-center gap-1.5 truncate flex-1`}>
                    {model.success ? (
                      <CheckCircle className={`h-3 w-3 sm:h-3.5 sm:w-3.5 ${classes.icon} flex-shrink-0`} />
                    ) : (
                      <XCircle className="h-3 w-3 sm:h-3.5 sm:w-3.5 text-red-500 flex-shrink-0" />
                    )}
                    <span className="truncate">{model.name}</span>
                  </h5>
                  {isBest && (
                    <span className="px-1.5 py-0.5 rounded text-[9px] sm:text-[10px] font-bold bg-indigo-600 text-white flex-shrink-0 ml-2">
                      BEST
                    </span>
                  )}
                </div>
                <div className="flex items-center flex-wrap gap-2 text-[9px] sm:text-[10px] text-gray-600">
                  <span className="flex items-center gap-1">
                    <Clock className="h-2.5 w-2.5 sm:h-3 sm:w-3" />
                    {(model.response_time_ms / 1000).toFixed(2)}s
                  </span>
                  {model.token_usage && (
                    <span className="hidden sm:inline">
                      {model.token_usage.prompt_tokens + model.token_usage.completion_tokens} tokens
                    </span>
                  )}
                </div>
              </div>
              <div className="p-3">
                {model.success ? (
                  <div>
                    <div
                      className={`text-[11px] sm:text-xs text-gray-700 leading-relaxed ${
                        !isExpanded ? 'line-clamp-6' : ''
                      }`}
                    >
                      <div className="prose prose-sm max-w-none">
                        <ReactMarkdown
                          components={{
                            p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                            strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
                            ul: ({ children }) => <ul className="space-y-1 ml-3 my-1.5">{children}</ul>,
                            ol: ({ children }) => <ol className="space-y-1 ml-3 my-1.5">{children}</ol>,
                            li: ({ children }) => <li className="text-gray-700 text-[11px] sm:text-xs">{children}</li>,
                            h3: ({ children }) => <h3 className="font-semibold text-gray-900 mt-2 mb-1 text-xs">{children}</h3>,
                          }}
                        >
                          {model.content}
                        </ReactMarkdown>
                      </div>
                    </div>
                    {model.content.length > 300 && (
                      <button
                        type="button"
                        onClick={() => setExpandedModel(isExpanded ? null : model.name)}
                        className="mt-2 text-[11px] sm:text-xs text-indigo-600 hover:text-indigo-700 font-medium flex items-center gap-1"
                      >
                        {isExpanded ? (
                          <>
                            <ChevronUp className="h-3 w-3" />
                            Show less
                          </>
                        ) : (
                          <>
                            <ChevronDown className="h-3 w-3" />
                            Show more
                          </>
                        )}
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="text-[11px] sm:text-xs text-red-600 bg-red-50 p-2 rounded">
                    <p className="font-medium mb-1">Error:</p>
                    <p className="text-red-700 break-words">{model.error || 'Unknown error'}</p>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Performance Summary */}
      <div className="rounded-lg border border-gray-200 bg-gradient-to-br from-gray-50 to-gray-100 p-3 sm:p-4">
        <h5 className="text-xs sm:text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
          <Clock className="h-4 w-4 text-gray-500" />
          Performance Comparison
        </h5>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
          {result.models.map((model, index) => {
            const color = getModelColor(model.name);
            const classes = getColorClasses(color);
            const modelShortName = model.name.split(' ')[0];
            return (
              <div 
                key={index} 
                className="flex items-center justify-between sm:block p-2 sm:p-0 bg-white sm:bg-transparent rounded sm:rounded-none"
              >
                <div className="flex items-center gap-2 sm:mb-1">
                  {model.success ? (
                    <CheckCircle className={`h-3.5 w-3.5 ${classes.icon}`} />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 text-red-500" />
                  )}
                  <p className={`font-semibold ${classes.text} text-[11px] sm:text-xs`}>
                    {modelShortName}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <p className="text-gray-600 text-[11px] sm:text-xs font-medium">
                    {model.success ? (
                      <>
                        <span className="sm:hidden">{(model.response_time_ms / 1000).toFixed(2)}s</span>
                        <span className="hidden sm:inline">{model.response_time_ms}ms</span>
                      </>
                    ) : (
                      <span className="text-red-600">Failed</span>
                    )}
                  </p>
                  {model.token_usage && model.success && (
                    <span className="hidden lg:inline text-[10px] text-gray-500">
                      ({model.token_usage.prompt_tokens + model.token_usage.completion_tokens} tok)
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
