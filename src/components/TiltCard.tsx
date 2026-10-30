import React, { useState } from 'react';

export const TiltCard: React.FC<{
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
}> = ({ children, className = '', disabled = false }) => {
  const [transform, setTransform] = useState<string>('perspective(900px) rotateX(0deg) rotateY(0deg)');

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (disabled) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;
    const rotateX = ((y - centerY) / centerY) * -6.5;
    const rotateY = ((x - centerX) / centerX) * 6.5;
    setTransform(`perspective(900px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) scale3d(1.015, 1.015, 1.015)`);
  };

  const handleMouseLeave = () => {
    setTransform('perspective(900px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)');
  };

  return (
    <div
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{
        transform,
        transition: 'transform 0.22s cubic-bezier(0.22, 1, 0.36, 1)',
        willChange: 'transform',
      }}
      className={className}
    >
      {children}
    </div>
  );
};

