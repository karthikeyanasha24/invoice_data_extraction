'use client';

import { useState } from 'react';
import { Sparkles, Clock, CheckCircle, XCircle, Loader2 } from 'lucide-react';

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

  return (
    <div className="space-y-4 mt-4">
      {/* Synthesized Answer - Prominent Display */}
      <div className="rounded-xl border-2 border-indigo-200 bg-white shadow-md overflow-hidden">
        <div className="px-4 py-3 border-b border-indigo-100 bg-indigo-50 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-indigo-600" />
            <h4 className="text-sm font-semibold text-indigo-900">Best Answer (Synthesized)</h4>
          </div>
          <div className="flex items-center gap-3 text-xs text-indigo-600">
            <span className="flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              {result.total_time_ms}ms
            </span>
            <span className="px-2 py-0.5 rounded-full bg-indigo-100 font-medium">
              Best: {result.best_model}
            </span>
          </div>
        </div>
        <div className="p-4">
          <p className="text-gray-800 leading-relaxed whitespace-pre-wrap">{result.synthesized_answer}</p>
        </div>
      </div>

      {/* Individual Model Responses - 3 Columns */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {result.models.map((model, index) => {
          const color = getModelColor(model.name);
          const classes = getColorClasses(color);
          const isExpanded = expandedModel === model.name;
          const isBest = model.name === result.best_model;

          return (
            <div
              key={index}
              className={`rounded-xl border ${classes.border} bg-white shadow-sm overflow-hidden transition-all ${
                isBest ? 'ring-2 ring-offset-2 ring-indigo-400' : ''
              }`}
            >
              <div className={`px-3 py-2.5 border-b ${classes.border} ${classes.bg}`}>
                <div className="flex items-center justify-between mb-1.5">
                  <h5 className={`text-xs font-semibold ${classes.text} flex items-center gap-1.5`}>
                    {model.success ? (
                      <CheckCircle className={`h-3.5 w-3.5 ${classes.icon}`} />
                    ) : (
                      <XCircle className="h-3.5 w-3.5 text-red-500" />
                    )}
                    {model.name}
                  </h5>
                  {isBest && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-600 text-white">
                      BEST
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 text-[10px] text-gray-600">
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {model.response_time_ms}ms
                  </span>
                  {model.token_usage && (
                    <span>
                      {model.token_usage.prompt_tokens + model.token_usage.completion_tokens} tokens
                    </span>
                  )}
                </div>
              </div>
              <div className="p-3">
                {model.success ? (
                  <div>
                    <p
                      className={`text-xs text-gray-700 leading-relaxed ${
                        !isExpanded ? 'line-clamp-6' : ''
                      }`}
                    >
                      {model.content}
                    </p>
                    {model.content.length > 300 && (
                      <button
                        type="button"
                        onClick={() => setExpandedModel(isExpanded ? null : model.name)}
                        className="mt-2 text-xs text-indigo-600 hover:text-indigo-700 font-medium"
                      >
                        {isExpanded ? 'Show less' : 'Show more'}
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="text-xs text-red-600 bg-red-50 p-2 rounded">
                    <p className="font-medium">Error:</p>
                    <p>{model.error || 'Unknown error'}</p>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Performance Summary */}
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
        <h5 className="text-xs font-semibold text-gray-700 mb-2">Performance Comparison</h5>
        <div className="grid grid-cols-3 gap-4 text-xs">
          {result.models.map((model, index) => {
            const color = getModelColor(model.name);
            const classes = getColorClasses(color);
            return (
              <div key={index}>
                <p className={`font-medium ${classes.text} mb-0.5`}>{model.name.split(' ')[0]}</p>
                <p className="text-gray-600">
                  {model.success ? `${model.response_time_ms}ms` : 'Failed'}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
