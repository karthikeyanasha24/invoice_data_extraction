'use client';

import { ChevronLeft, ChevronRight, MoreHorizontal } from 'lucide-react';
import { cn } from '@/lib/utils';

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  itemsPerPage?: number;
  totalItems?: number;
  showInfo?: boolean;
}

export default function Pagination({
  currentPage,
  totalPages,
  onPageChange,
  itemsPerPage = 10,
  totalItems,
  showInfo = true
}: PaginationProps) {
  const getVisiblePages = () => {
    const delta = 2;
    const range = [];
    const rangeWithDots = [];

    for (let i = Math.max(2, currentPage - delta); i <= Math.min(totalPages - 1, currentPage + delta); i++) {
      range.push(i);
    }

    if (currentPage - delta > 2) {
      rangeWithDots.push(1, '...');
    } else {
      rangeWithDots.push(1);
    }

    rangeWithDots.push(...range);

    if (currentPage + delta < totalPages - 1) {
      rangeWithDots.push('...', totalPages);
    } else if (totalPages > 1) {
      rangeWithDots.push(totalPages);
    }

    return rangeWithDots;
  };

  const visiblePages = getVisiblePages();
  const startItem = (currentPage - 1) * itemsPerPage + 1;
  const endItem = totalItems ? Math.min(currentPage * itemsPerPage, totalItems) : currentPage * itemsPerPage;

  if (totalPages <= 1) {
    return showInfo && totalItems ? (
      <div className="flex items-center justify-center px-3 sm:px-4 py-3 text-xs sm:text-sm text-gray-700">
        <div>
          Showing {totalItems} {totalItems === 1 ? 'item' : 'items'}
        </div>
      </div>
    ) : null;
  }

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between px-3 sm:px-4 py-3 bg-white border-t border-gray-200 space-y-3 sm:space-y-0">
      {/* Items Info */}
      {showInfo && totalItems && (
        <div className="text-xs sm:text-sm text-gray-700 order-2 sm:order-1">
          Showing {startItem} to {endItem} of {totalItems} results
        </div>
      )}

      {/* Pagination Controls */}
      <div className="flex items-center space-x-1 order-1 sm:order-2">
        {/* Previous Button */}
        <button
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage === 1}
          className={cn(
            "p-2 rounded-md transition-colors",
            currentPage === 1
              ? "text-gray-400 cursor-not-allowed"
              : "text-gray-700 hover:bg-gray-100"
          )}
        >
          <ChevronLeft className="h-4 w-4" />
        </button>

        {/* Page Numbers */}
        <div className="hidden sm:flex items-center space-x-1">
          {visiblePages.map((page, index) => {
            if (page === '...') {
              return (
                <span key={`dots-${index}`} className="px-2 sm:px-3 py-2 text-gray-500">
                  <MoreHorizontal className="h-4 w-4" />
                </span>
              );
            }

            const pageNumber = page as number;
            const isCurrentPage = pageNumber === currentPage;

            return (
              <button
                key={pageNumber}
                onClick={() => onPageChange(pageNumber)}
                className={cn(
                  "px-2 sm:px-3 py-2 text-sm font-medium rounded-md transition-colors",
                  isCurrentPage
                    ? "bg-blue-600 text-white"
                    : "text-gray-700 hover:bg-gray-100"
                )}
              >
                {pageNumber}
              </button>
            );
          })}
        </div>

        {/* Mobile Page Indicator */}
        <div className="flex sm:hidden items-center px-3 py-2 text-sm text-gray-700">
          Page {currentPage} of {totalPages}
        </div>

        {/* Next Button */}
        <button
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage === totalPages}
          className={cn(
            "p-2 rounded-md transition-colors",
            currentPage === totalPages
              ? "text-gray-400 cursor-not-allowed"
              : "text-gray-700 hover:bg-gray-100"
          )}
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

